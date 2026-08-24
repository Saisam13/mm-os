"""Computed approver — docs/07's central rule, and the escalation acceptance test.

Uses the real seeded personas (app/org_chart.SEED_PERSONAS): MM88's manager is MM81, taken
verbatim from backend/app/demo_seed.py — the fixture's one real manager relationship among
the five demo personas.
"""
import pytest

from app.org_chart import NoApproverFound, compute_approver, default_seed


def test_mm88_escalates_to_mm81_the_real_manager():
    """MM88 (MAMATESH UDAY NAIK, Projects) raises a request; MM81 (Chandrashekhar Keshav
    Kalvit, Projects, L4 Div Head) is their real manager in the fixture and qualifies —
    the chain resolves to MM81, not MM88 themselves."""
    client = default_seed()
    approver = compute_approver("user:MM88", client)
    assert approver.sub == "user:MM81"
    assert approver.employee_code == "MM81"


def test_mm81_raising_own_request_has_no_manager_and_raises():
    """Acceptance test: "a requester who is their own computed approver sees it escalate
    one level." MM81 qualifies on their own approval_level, so the naive walk would stop at
    the requester themselves — compute_approver must skip that. The fixture is honest about
    MM81 having no manager above them (see demo_seed.py), so escalating past self finds
    nobody and raises — app/routing.py is what falls back to the configured
    ApprovalDefault (MM-ITADMIN) from here, not this function."""
    client = default_seed()
    with pytest.raises(NoApproverFound):
        compute_approver("user:MM81", client)


def test_is_approver_override_qualifies_regardless_of_level(monkeypatch):
    from app.org_chart import PersonNode, SeedOrgChartClient

    requester = PersonNode(sub="u:r", employee_code="MM90", full_name="R", department="X",
                            approval_level="Operational", is_approver=False, manager_sub="u:override")
    override = PersonNode(sub="u:override", employee_code="MM91", full_name="Override", department="X",
                           approval_level=None, is_approver=True, manager_sub=None)
    client = SeedOrgChartClient({requester.sub: requester, override.sub: override})
    approver = compute_approver("u:r", client)
    assert approver.sub == "u:override"
