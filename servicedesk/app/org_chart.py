"""Computed-approver logic — docs/07-service-desk.md's central rule.

    the approver is computed, not chosen: employees.manager_id of the requester, escalating
    up bands until someone with a qualifying approval_level is found; is_approver overrides
    from the sheet are honoured. a requester can never approve their own request, even if
    they are the computed approver — it escalates one level.

Computing this needs a walk up the MM OS org chart (manager_id, approval_level, is_approver
per docs/02-data-model.md's `employees` table). Service Desk has no foreign key into MM OS
and must not duplicate that table in its own database — so this module talks to an
`OrgChartClient` seam, exactly the way app/mmos_seam.py is a seam over auth.

**Contract gap (see `## Contract objections` in the handoff):** neither
docs/03-api-contract.md nor docs/05-service-integration.md expose an endpoint a service can
call to walk another user's manager chain. `/api/admin/employees` exists but requires
`is_platform_admin`, which Service Desk's service identity does not hold and should not be
granted just for this. `HttpOrgChartClient` below calls an endpoint this module assumes will
exist — `GET /api/org/chain?sub=...`, authenticated with the service key like the heartbeat
and revocation calls — and is untested against a real MM OS instance because that endpoint
does not exist yet. `SeedOrgChartClient` is what every test in this repo actually runs
against.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from .config import settings


class NoApproverFound(Exception):
    """Walked the whole chain (including the top of the org) and nobody qualifies."""


@dataclass(frozen=True)
class PersonNode:
    sub: str
    employee_code: str
    full_name: str
    department: str
    approval_level: str | None
    is_approver: bool
    manager_sub: str | None
    email: str | None = None


def qualifies(node: PersonNode) -> bool:
    """A node has real approval authority if the sheet marked them an override, or their
    approval_level is a real tier rather than the "no authority" default.

    docs/02-data-model.md's schema comment gives exactly three example values —
    "L3 (HOD)", "L5 (Apex)", "Operational" — and "Operational" reads as the default for
    everyone without a funding-approval role, not a tier. This module treats any non-empty
    approval_level other than "Operational" as qualifying. That reading is not spelled out
    verbatim in docs/07 — see `## Assumptions`.
    """
    if node.is_approver:
        return True
    return bool(node.approval_level) and node.approval_level != "Operational"


class OrgChartClient(Protocol):
    def chain_for(self, sub: str) -> list[PersonNode]:
        """Requester-first list: chain[0] is the requester, chain[1] their manager, and so
        on to the top of the org (manager_sub is None on the last node)."""
        ...


class SeedOrgChartClient:
    """A tiny in-memory fixture — not a duplicated employees table, just enough shape to run
    this service and its tests standalone while the real lookup does not exist yet. Never
    used in production (`ORG_CHART_MODE=http` calls the real thing once it lands)."""

    def __init__(self, people: dict[str, PersonNode]):
        self._people = people

    def chain_for(self, sub: str) -> list[PersonNode]:
        chain: list[PersonNode] = []
        seen: set[str] = set()
        current = sub
        while current and current not in seen:
            seen.add(current)
            node = self._people.get(current)
            if node is None:
                break
            chain.append(node)
            current = node.manager_sub
        return chain


# A minimal fixture org, shaped like the real one (docs/01, P-Spoke department):
# operator -> supervisor -> HOD -> Apex. Shared by default_seed() (below), the manual-testing
# dev-token endpoint (app/routers/mmos.py), and tests/conftest.py, so all three agree on who
# the seeded people are without three copies of the same data drifting apart. Not demo data
# beyond what the acceptance tests and manual verification need.
SEED_PERSONAS = {
    "operator": dict(sub="user:op-1", employee_code="MM19", full_name="P-Spoke Operator",
                      department="P-Spoke", division="Production", band="NON L",
                      approval_level="Operational", is_approver=False, email=None),
    "supervisor": dict(sub="user:sup-1", employee_code="MM05", full_name="P-Spoke Supervisor",
                        department="P-Spoke", division="Production", band="L2",
                        approval_level="Operational", is_approver=False, email="supervisor@m-mines.com"),
    "hod": dict(sub="user:hod-1", employee_code="MM02", full_name="P-Spoke HOD",
                department="P-Spoke", division="Production", band="L3",
                approval_level="L3 (HOD)", is_approver=False, email="hod@m-mines.com"),
    "apex": dict(sub="user:apex-1", employee_code="MM01", full_name="Apex Approver",
                 department="Corporate", division="Corporate", band="L5",
                 approval_level="L5 (Apex)", is_approver=False, email="apex@m-mines.com"),
}
SEED_MANAGER_OF = {"operator": "supervisor", "supervisor": "hod", "hod": "apex", "apex": None}


def default_seed() -> SeedOrgChartClient:
    """The `OrgChartClient` fixture built from `SEED_PERSONAS`. An HOD who raises their own
    request must escalate past themselves to Apex — see test_approver.py."""
    node_fields = {"sub", "employee_code", "full_name", "department", "approval_level", "is_approver", "email"}
    people: dict[str, PersonNode] = {}
    for key, data in SEED_PERSONAS.items():
        manager_key = SEED_MANAGER_OF[key]
        manager_sub = SEED_PERSONAS[manager_key]["sub"] if manager_key else None
        node_kwargs = {k: v for k, v in data.items() if k in node_fields}
        people[data["sub"]] = PersonNode(manager_sub=manager_sub, **node_kwargs)
    return SeedOrgChartClient(people)


class HttpOrgChartClient:
    """Calls `GET /api/agent/org/chain?sub=...` with the service key -- added by B1
    (`backend/app/routers/agent.py::org_chain`, seam inventory section B) to close the gap
    this class used to flag as untested against anything real. Mounted under `/api/agent`,
    not the bare `/api/org/chain` this class originally assumed, matching the prefix every
    other service-authenticated MM OS call already uses (heartbeat, config, revocations) --
    see handoff/b1-assembly.md ## Deviations for why the bare path was not used instead."""

    def __init__(self, os_url: str, service_key: str):
        self._os_url = os_url.rstrip("/")
        self._service_key = service_key

    def chain_for(self, sub: str) -> list[PersonNode]:
        resp = httpx.get(
            f"{self._os_url}/api/agent/org/chain",
            params={"sub": sub},
            headers={"Authorization": f"Bearer {self._service_key}"},
            timeout=5.0,
        )
        resp.raise_for_status()
        return [PersonNode(**row) for row in resp.json()["chain"]]


_client: OrgChartClient | None = None


def get_org_chart_client() -> OrgChartClient:
    global _client
    if _client is None:
        cfg = settings()
        if cfg.org_chart_mode == "http":
            _client = HttpOrgChartClient(cfg.mmos_os_url, cfg.mmos_service_key)
        else:
            _client = default_seed()
    return _client


def set_org_chart_client(client: OrgChartClient) -> None:
    """Test seam — swap in a fixture chain per-test."""
    global _client
    _client = client


def get_person(sub: str, client: OrgChartClient | None = None) -> PersonNode | None:
    """Used for notifications: resolving *whose* email a given sub is, regardless of who the
    caller is. `chain_for` always returns the requested sub first."""
    client = client or get_org_chart_client()
    chain = client.chain_for(sub)
    return chain[0] if chain else None


def list_known_people(client: OrgChartClient | None = None) -> list[PersonNode]:
    """Directory listing for the Administration page's person pickers (Users & Roles,
    Approval Routing's approver/default fields) — pick a known person rather than typing a
    raw `sub`. `SeedOrgChartClient` can enumerate its fixture; a real MM OS directory-listing
    endpoint is the same contract gap `HttpOrgChartClient.chain_for` already flags (no
    endpoint exists for a service to look up people it doesn't already have a `sub` for) —
    `http` mode returns an empty list rather than guessing at one, same as everywhere else in
    this module that hits that gap."""
    client = client or get_org_chart_client()
    if isinstance(client, SeedOrgChartClient):
        return list(client._people.values())
    return []


def compute_approver(requester_sub: str, client: OrgChartClient | None = None) -> PersonNode:
    """Walk the chain requester-first. Skip the requester themselves even if they qualify —
    that is the literal self-approval rule — and keep climbing until someone else qualifies.

    This single loop is deliberately how both docs/07 rules are satisfied at once: "walk
    manager_id up ... until someone with a qualifying approval_level is found" and "a
    requester can never approve their own request, even if they are the computed approver —
    it escalates one level."
    """
    client = client or get_org_chart_client()
    chain = client.chain_for(requester_sub)
    for node in chain:
        if not qualifies(node):
            continue
        if node.sub == requester_sub:
            continue
        return node
    raise NoApproverFound(f"no qualifying approver found above {requester_sub}")
