"""Role files: one JSON document that declares a service's roles, what each role may do, and
optionally who gets which role.

A service's access model used to live only in whoever last clicked "Add role". A role file
makes it a reviewable, versionable artefact instead: export it, edit it, import it back, and
the dry run shows exactly what would change before anything is written. The committed files
live in `app/role_files/<slug>.json` and ship inside the image.

    {
      "format": "mmos-roles/1",
      "service": "itemcode",
      "permissions": {"items.view": "Browse and search the item master", ...},
      "roles": [
        {"key": "associate", "name": "Associate", "description": "...", "default": true,
         "permissions": ["items.view", "items.create"], "replaces": ["viewer"]},
        ...
      ],
      "remove_unlisted": false,
      "assign": {
        "mode": "missing",
        "rules": [{"platform_admin": true, "role": "admin"},
                  {"is_approver": true, "role": "manager"}],
        "people": {"MM-ITADMIN": "admin"},
        "default": "associate"
      }
    }

Semantics, in the order they are applied:

1. `permissions` replaces the service's permission catalog. A role may only list keys from it.
2. Each role is created or updated by `key`. List order is the access order, lowest first.
3. `replaces` moves every grant on the named old roles onto this one, then deletes them.
   This is how `viewer` becomes `associate` without anyone losing access.
4. `remove_unlisted: true` deletes roles the file does not mention, but only those nobody
   holds; a role with grants must be `replaces`-ed instead, and the import says so.
5. `assign` gives people a role. `people` (employee code or login email) wins, then the first
   matching rule, then `default`. `mode: "missing"` only touches people with no grant on this
   service, so hand-set roles survive a re-import; `mode: "all"` re-derives everyone.
   Omitting `default` means people who match nothing are left alone.

Rule keys: `platform_admin` (bool), `is_approver` (bool), `has_approval_level` (bool),
`band` (list), `department` (list). Every key in a rule must match.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .models import Employee, Grant, Revocation, Service, ServiceRole, User

FORMAT = "mmos-roles/1"
ROLE_FILES_DIR = Path(__file__).parent / "role_files"
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_PERM_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_RULE_KEYS = {"platform_admin", "is_approver", "has_approval_level", "band", "department", "role"}
_REVOCATION_TTL = timedelta(hours=2)


class RoleFileError(ValueError):
    """The file is malformed. `problems` lists every issue, not just the first."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class RolePlan:
    """What an import would do. Returned by a dry run and by the real run alike."""

    service: str
    catalog_changed: bool = False
    roles_created: list[str] = field(default_factory=list)
    roles_updated: list[str] = field(default_factory=list)
    roles_removed: list[str] = field(default_factory=list)
    grants_moved: list[dict] = field(default_factory=list)
    grants_created: list[dict] = field(default_factory=list)
    grants_changed: list[dict] = field(default_factory=list)
    unchanged_people: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "service": self.service,
            "catalog_changed": self.catalog_changed,
            "roles_created": self.roles_created,
            "roles_updated": self.roles_updated,
            "roles_removed": self.roles_removed,
            "grants_moved": self.grants_moved,
            "grants_created": self.grants_created,
            "grants_changed": self.grants_changed,
            "unchanged_people": self.unchanged_people,
            "warnings": self.warnings,
        }


# ── validation ────────────────────────────────────────────────────────────────
def validate(doc: dict, *, slug: str | None = None) -> dict:
    """Return a normalised copy of `doc`, or raise RoleFileError listing every problem."""
    p: list[str] = []
    if not isinstance(doc, dict):
        raise RoleFileError(["the file must be a JSON object"])
    if doc.get("format", FORMAT) != FORMAT:
        p.append(f"format must be {FORMAT!r}")
    service = doc.get("service")
    if not isinstance(service, str) or not service:
        p.append("service (the slug) is required")
    elif slug and service != slug:
        p.append(f"this file is for {service!r}, not {slug!r}")

    catalog = doc.get("permissions", {})
    if not isinstance(catalog, dict):
        p.append("permissions must be an object of {key: meaning}")
        catalog = {}
    for k, v in catalog.items():
        if not _PERM_RE.match(str(k)):
            p.append(f"permission key {k!r} must be lowercase letters, digits, . _ : -")
        if not isinstance(v, str):
            p.append(f"permission {k!r} needs a text meaning")

    roles_in = doc.get("roles")
    roles: list[dict] = []
    if not isinstance(roles_in, list) or not roles_in:
        p.append("roles must be a non-empty list")
        roles_in = []
    seen: set[str] = set()
    for i, r in enumerate(roles_in):
        where = f"roles[{i}]"
        if not isinstance(r, dict):
            p.append(f"{where} must be an object")
            continue
        key = r.get("key")
        if not isinstance(key, str) or not _KEY_RE.match(key):
            p.append(f"{where}.key must be lowercase letters, digits and _ (max 32)")
            continue
        where = f"role {key!r}"
        if key in seen:
            p.append(f"{where} is listed twice")
        seen.add(key)
        name = r.get("name")
        if not isinstance(name, str) or not name.strip():
            p.append(f"{where} needs a name")
        perms = r.get("permissions", [])
        if not isinstance(perms, list):
            p.append(f"{where}.permissions must be a list")
            perms = []
        unknown = [x for x in perms if x not in catalog]
        if unknown:
            p.append(f"{where} lists permissions not in the catalog: {', '.join(map(str, unknown))}")
        replaces = r.get("replaces", [])
        if not isinstance(replaces, list) or not all(isinstance(x, str) for x in replaces):
            p.append(f"{where}.replaces must be a list of role keys")
            replaces = []
        roles.append({
            "key": key,
            "name": (name or "").strip(),
            "description": (r.get("description") or None),
            "default": bool(r.get("default", False)),
            "permissions": list(dict.fromkeys(perms)),
            "replaces": replaces,
        })
    if sum(1 for r in roles if r["default"]) > 1:
        p.append("only one role may be the default")
    for r in roles:
        clash = [x for x in r["replaces"] if x in seen]
        if clash:
            p.append(f"role {r['key']!r} cannot replace {', '.join(clash)}: still listed in roles")

    assign = doc.get("assign")
    if assign is not None:
        if not isinstance(assign, dict):
            p.append("assign must be an object")
            assign = None
        else:
            mode = assign.get("mode", "missing")
            if mode not in ("missing", "all"):
                p.append("assign.mode must be 'missing' or 'all'")
            for i, rule in enumerate(assign.get("rules", []) or []):
                if not isinstance(rule, dict) or rule.get("role") not in seen:
                    p.append(f"assign.rules[{i}] must name a role from this file")
                    continue
                bad = set(rule) - _RULE_KEYS
                if bad:
                    p.append(f"assign.rules[{i}] has unknown keys: {', '.join(sorted(bad))}")
            people = assign.get("people", {}) or {}
            if not isinstance(people, dict):
                p.append("assign.people must be an object of {employee code or email: role}")
            else:
                for who, role in people.items():
                    if role not in seen:
                        p.append(f"assign.people[{who!r}] names unknown role {role!r}")
            default = assign.get("default")
            if default is not None and default not in seen:
                p.append(f"assign.default {default!r} is not a role in this file")

    if p:
        raise RoleFileError(p)
    return {
        "format": FORMAT,
        "service": service,
        "permissions": {str(k): v for k, v in catalog.items()},
        "roles": roles,
        "remove_unlisted": bool(doc.get("remove_unlisted", False)),
        "assign": assign,
    }


def committed(slug: str) -> dict | None:
    """The committed role file for `slug`, or None if there is none."""
    path = ROLE_FILES_DIR / f"{slug}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ── export ────────────────────────────────────────────────────────────────────
def export(service: Service) -> dict:
    """The service's current roles as a role file. Never includes people."""
    return {
        "format": FORMAT,
        "service": service.slug,
        "permissions": dict(service.permission_catalog or {}),
        "roles": [
            {
                "key": r.key,
                "name": r.name,
                "description": r.description,
                "default": r.is_default,
                "permissions": list(r.permissions or []),
            }
            for r in service.roles
        ],
    }


# ── assignment ────────────────────────────────────────────────────────────────
def _rule_matches(rule: dict, user: User, emp: Employee) -> bool:
    if "platform_admin" in rule and bool(user.is_platform_admin) != bool(rule["platform_admin"]):
        return False
    if "is_approver" in rule and bool(emp.is_approver) != bool(rule["is_approver"]):
        return False
    if "has_approval_level" in rule and bool(emp.approval_level) != bool(rule["has_approval_level"]):
        return False
    if "band" in rule and emp.band not in (rule["band"] or []):
        return False
    if "department" in rule and emp.hr_department not in (rule["department"] or []):
        return False
    return True


def source_for(assign: dict, user: User, emp: Employee) -> tuple[str | None, str | None]:
    """(role, where it came from): "people", "rule", "default", or (None, None)."""
    people = {str(k).lower(): v for k, v in (assign.get("people") or {}).items()}
    for ident in (emp.employee_code, user.login_email, emp.work_email):
        if ident and ident.lower() in people:
            return people[ident.lower()], "people"
    for rule in assign.get("rules") or []:
        if _rule_matches(rule, user, emp):
            return rule["role"], "rule"
    default = assign.get("default")
    return (default, "default") if default else (None, None)


def role_for(assign: dict, user: User, emp: Employee) -> str | None:
    return source_for(assign, user, emp)[0]


def assign_roles(
    db: OrmSession,
    service: Service,
    assign: dict,
    plan: RolePlan,
    *,
    actor: User | None,
    mode: str = "missing",
    people_override: bool = False,
    only_user_ids: set[uuid.UUID] | None = None,
    skip: set[str] | None = None,
    reason: str = "role file",
) -> None:
    """Give people a role on `service` from an `assign` block. Shared by the role-file import
    and the people-sheet upload (app/people_sheet.py), so there is one assignment engine.

    `mode: "missing"` only touches people with no grant here; `"all"` re-derives everyone.
    `people_override` lets a role named for a person in `people` replace an existing grant
    even in "missing" mode (the sheet's "a filled-in cell wins, blanks only fill gaps").
    `only_user_ids` limits the run to those users. `skip` holds "EMPLOYEE_CODE:slug" keys the
    admin unticked in the dry run; those people are left exactly as they are."""
    by_key = {r.key: r for r in db.scalars(select(ServiceRole).where(ServiceRole.service_id == service.id))}
    rank = {r.key: r.sort_order for r in by_key.values()}
    grants = {g.user_id: g for g in db.scalars(select(Grant).where(Grant.service_id == service.id))}
    rows = db.execute(select(User, Employee).join(Employee, User.employee_id == Employee.id)).all()
    matched_people: set[str] = set()
    people_keys = {str(k).lower() for k in (assign.get("people") or {})}
    now = datetime.now(timezone.utc)
    for user, emp in rows:
        if only_user_ids is not None and user.id not in only_user_ids:
            continue
        for ident in (emp.employee_code, user.login_email, emp.work_email):
            if ident and ident.lower() in people_keys:
                matched_people.add(ident.lower())
        key, source = source_for(assign, user, emp)
        if key is None:
            continue
        if skip and f"{emp.employee_code}:{service.slug}".lower() in skip:
            plan.unchanged_people += 1
            continue
        target = by_key.get(key)
        if target is None:
            plan.warnings.append(f"{emp.employee_code}: {service.slug} has no role {key!r}")
            continue
        who = {"user_id": str(user.id), "name": emp.full_name, "employee_code": emp.employee_code,
               "source": source}
        g = grants.get(user.id)
        if g is None:
            db.add(Grant(user_id=user.id, service_id=service.id, service_role_id=target.id,
                         granted_by=actor.id if actor else None, reason=reason))
            plan.grants_created.append({**who, "role": key})
        elif g.service_role_id != target.id and (mode == "all" or (people_override and source == "people")):
            old_key = next((k for k, r in by_key.items() if r.id == g.service_role_id), "?")
            g.service_role_id = target.id
            g.granted_by = actor.id if actor else None
            g.reason = reason
            a, b = rank.get(old_key, 0), rank.get(key, 0)
            direction = "up" if b > a else "down" if b < a else "change"  # equal: order unknown
            plan.grants_changed.append({**who, "from": old_key, "to": key, "direction": direction})
            db.add(Revocation(subject=user.subject, service_id=service.id, reason="role_changed",
                              revoked_by=actor.id if actor else None, revoked_at=now,
                              purge_after=now + _REVOCATION_TTL))
        else:
            plan.unchanged_people += 1
    if only_user_ids is None:
        for missing in sorted(people_keys - matched_people):
            plan.warnings.append(f"assign.people: nobody in MM OS matches {missing!r}")
    db.flush()


# ── apply ─────────────────────────────────────────────────────────────────────
def apply(
    db: OrmSession,
    service: Service,
    doc: dict,
    *,
    actor: User | None,
    dry_run: bool,
    assign_mode: str | None = None,
) -> RolePlan:
    """Apply a validated role file. With `dry_run` the session is rolled back by the caller;
    everything is still computed against real rows so the preview is exact."""
    plan = RolePlan(service=service.slug)
    now = datetime.now(timezone.utc)

    if dict(service.permission_catalog or {}) != doc["permissions"]:
        plan.catalog_changed = True
        service.permission_catalog = doc["permissions"]

    existing = {r.key: r for r in db.scalars(select(ServiceRole).where(ServiceRole.service_id == service.id))}
    by_key: dict[str, ServiceRole] = {}
    for order, spec in enumerate(doc["roles"]):
        role = existing.get(spec["key"])
        fields = dict(
            name=spec["name"], description=spec["description"], is_default=spec["default"],
            permissions=spec["permissions"], sort_order=(order + 1) * 10,
        )
        if role is None:
            role = ServiceRole(service_id=service.id, key=spec["key"], **fields)
            db.add(role)
            plan.roles_created.append(spec["key"])
        else:
            changed = any(getattr(role, k) != v for k, v in fields.items() if k != "sort_order")
            for k, v in fields.items():
                setattr(role, k, v)
            if changed:
                plan.roles_updated.append(spec["key"])
        by_key[spec["key"]] = role
    db.flush()

    def _revoke(user_id: uuid.UUID, reason: str) -> None:
        user = db.get(User, user_id)
        db.add(Revocation(subject=user.subject, service_id=service.id, reason=reason,
                          revoked_by=actor.id if actor else None, revoked_at=now,
                          purge_after=now + _REVOCATION_TTL))

    # replaces: move grants, then drop the old role
    for spec in doc["roles"]:
        for old_key in spec["replaces"]:
            old = existing.get(old_key)
            if old is None:
                continue
            for g in db.scalars(select(Grant).where(Grant.service_role_id == old.id)):
                g.service_role_id = by_key[spec["key"]].id
                plan.grants_moved.append({"user_id": str(g.user_id), "from": old_key, "to": spec["key"]})
                _revoke(g.user_id, "role_changed")
            db.flush()
            db.delete(old)
            plan.roles_removed.append(old_key)
    db.flush()

    if doc["remove_unlisted"]:
        replaced = {k for s in doc["roles"] for k in s["replaces"]}
        for key, role in existing.items():
            if key in by_key or key in replaced:
                continue
            held = db.scalar(select(Grant.id).where(Grant.service_role_id == role.id).limit(1))
            if held:
                plan.warnings.append(
                    f"kept role {key!r}: people still hold it; add it to a role's 'replaces' to move them"
                )
                continue
            db.delete(role)
            plan.roles_removed.append(key)
        db.flush()

    assign = doc.get("assign")
    if assign:
        assign_roles(db, service, assign, plan, actor=actor, mode=assign_mode or assign.get("mode", "missing"))

    return plan
