"""Employee-sheet importer. Owned by A1 (Identity). See docs/02-data-model.md "Seeding".

    python -m app.seed --xlsx <path> [--commit]

Dry run by default: prints a diff (new / changed / missing / conflicting) and writes
nothing. `--commit` applies it. Re-importing is idempotent and never silently orphans a
grant — nothing here ever deletes an Employee or a Grant; "missing" rows are only reported.

The functions in this module (`load_sheet_rows`, `compute_diff`, `apply_diff`,
`resolve_managers`) are also called directly by `routers/people.py`'s
`POST /api/admin/employees/import`, so the CLI and the admin-UI upload path share one
implementation instead of two copies that could drift.

Owner ruling, 24 Aug 2026 (handoff/ORCHESTRATOR.md "Owner decisions taken mid-run"):
every employee gets a local PIN account on import -- not just the ones with no corporate
Work Email. `docs/02-data-model.md`'s "no Work Email -> local_pin" line is the floor, not
the ceiling; see `apply_diff` and handoff/a1-identity.md ## Deviations for why.
"""
from __future__ import annotations

import argparse
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

import openpyxl
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as OrmSession

from .db import SessionLocal
from .models import AuditLog, Employee, Grant, Service, ServiceRole, User
from .security import hash_pin

SHEET_NAME = "Employee Role & Access Map"
DEFAULT_XLSX_PATH = Path(r"C:\Users\Anura\OneDrive\Desktop\Erp Imp\Employee_Role_Access_Mapping.xlsx")

PLATFORM_ADMIN_EMAIL = "itadmin@m-mines.com"

# Column headers, exactly as they appear in the sheet (docs/02-data-model.md "Seeding" table).
COL_CODE = "Employee Code"
COL_NAME = "Full Name"
COL_EMAIL = "Work Email"
COL_DEPT = "HR Department"
COL_DIVISION = "Division (Approval Matrix)"
COL_TITLE = "Job Title (New Org Structure)"
COL_BAND = "Band"
COL_APPROVAL = "Approval Level"
COL_ERP_ACCESS = "ERP-Based System Access (assigned role)"
COL_EXTRA_ACCESS = "Extra / Cross-Dept Report Access"
COL_OVERRIDE = "Special Approver Override"

TRACKED_FIELDS = (
    "full_name", "work_email", "hr_department", "division", "job_title",
    "band", "approval_level", "is_approver", "notes",
)

# Band-seniority ladder used only to guess a manager (division + "next band up"). Not in
# docs/02 — the sheet has no "reports to" column at all, so this is a heuristic, and a
# deliberately conservative one: ties and gaps are reported unresolved, never guessed.
# See handoff/a1-identity.md ## Assumptions for the exact reasoning and the two band
# spellings ("Ops", "NON L") that appear in the real sheet but not in docs/02's comment.
BAND_RANK = {"NON L": 0, "Ops": 0, "L1J": 1, "L1S": 2, "L2": 3, "L3": 4, "L4": 5, "L5": 6}


@dataclass
class EmployeeRow:
    employee_code: str
    full_name: str
    work_email: str | None
    hr_department: str
    division: str
    job_title: str
    band: str
    approval_level: str | None
    is_approver: bool
    notes: str | None
    erp_access_text: str | None
    extra_access_text: str | None


@dataclass
class ImportDiff:
    new: list[EmployeeRow] = field(default_factory=list)
    changed: list[tuple[EmployeeRow, dict]] = field(default_factory=list)
    missing_codes: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    proposed_grants: list[tuple[str, str, str]] = field(default_factory=list)


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def load_sheet_rows(source: str | Path | BinaryIO) -> list[EmployeeRow]:
    """`source` is a filesystem path (CLI) or a file-like object (the admin upload)."""
    wb = openpyxl.load_workbook(source, data_only=True, read_only=True)
    ws = wb[SHEET_NAME]
    all_rows = list(ws.iter_rows(values_only=True))
    if not all_rows:
        return []
    headers = [(_clean(h) or "") for h in all_rows[0]]
    col = {name: idx for idx, name in enumerate(headers)}

    required = (COL_CODE, COL_NAME, COL_EMAIL, COL_DEPT, COL_DIVISION, COL_TITLE, COL_BAND)
    missing = [c for c in required if c not in col]
    if missing:
        raise ValueError(f"Sheet is missing expected column(s): {missing}")

    def get(row, name):
        idx = col.get(name)
        return _clean(row[idx]) if idx is not None and idx < len(row) else None

    out: list[EmployeeRow] = []
    for row in all_rows[1:]:
        code = get(row, COL_CODE)
        if not code:
            continue  # blank trailing row
        override = get(row, COL_OVERRIDE)
        out.append(
            EmployeeRow(
                employee_code=code,
                full_name=get(row, COL_NAME) or "",
                work_email=get(row, COL_EMAIL),
                hr_department=get(row, COL_DEPT) or "",
                division=get(row, COL_DIVISION) or "",
                job_title=get(row, COL_TITLE) or "",
                band=get(row, COL_BAND) or "",
                approval_level=get(row, COL_APPROVAL),
                is_approver=override is not None,
                notes=override,
                erp_access_text=get(row, COL_ERP_ACCESS),
                extra_access_text=get(row, COL_EXTRA_ACCESS),
            )
        )
    return out


def compute_diff(db: OrmSession, rows: list[EmployeeRow]) -> ImportDiff:
    existing_by_code = {e.employee_code: e for e in db.scalars(select(Employee))}
    existing_by_email = {e.work_email: e for e in existing_by_code.values() if e.work_email}

    diff = ImportDiff()
    sheet_codes: set[str] = set()
    seen_emails: dict[str, str] = {}  # email -> first employee_code seen this import

    for r in rows:
        sheet_codes.add(r.employee_code)

        if r.work_email:
            dupe_code = seen_emails.get(r.work_email)
            if dupe_code and dupe_code != r.employee_code:
                diff.conflicts.append(
                    f"{r.employee_code}: work_email {r.work_email!r} also used by {dupe_code} in this sheet - skipped"
                )
                continue
            seen_emails[r.work_email] = r.employee_code

            other = existing_by_email.get(r.work_email)
            if other is not None and other.employee_code != r.employee_code:
                diff.conflicts.append(
                    f"{r.employee_code}: work_email {r.work_email!r} already belongs to "
                    f"{other.employee_code} in the database - skipped"
                )
                continue

        if r.erp_access_text or r.extra_access_text:
            text = " | ".join(t for t in (r.erp_access_text, r.extra_access_text) if t)
            diff.proposed_grants.append((r.employee_code, r.full_name, text))

        existing = existing_by_code.get(r.employee_code)
        if existing is None:
            diff.new.append(r)
            continue

        field_diff = {}
        for f in TRACKED_FIELDS:
            new_val = getattr(r, f)
            old_val = getattr(existing, f)
            if (old_val or None) != (new_val or None):
                field_diff[f] = (old_val, new_val)
        if field_diff:
            diff.changed.append((r, field_diff))

    diff.missing_codes = sorted(set(existing_by_code) - sheet_codes)
    return diff


def apply_diff(db: OrmSession, diff: ImportDiff) -> None:
    """Create new employees/users and update changed fields. Never deletes anything."""
    for r in diff.new:
        emp = Employee(
            employee_code=r.employee_code,
            full_name=r.full_name,
            work_email=r.work_email,
            hr_department=r.hr_department,
            division=r.division,
            job_title=r.job_title,
            band=r.band,
            approval_level=r.approval_level,
            is_approver=r.is_approver,
            notes=r.notes,
        )
        db.add(emp)
        db.flush()  # need emp.id for the User row

        # Owner ruling (handoff/ORCHESTRATOR.md "Owner decisions taken mid-run"): EVERY
        # employee gets a local PIN account on import, corporate work email included.
        # Employee-code + PIN is the universal day-one path so nobody waits on a mailbox;
        # Google sign-in is added later through the self-service link flow in
        # routers/auth.py (google_link_start / _complete_google_link), which sets
        # login_email and flips auth_type to 'google' while KEEPING this pin_hash so PIN
        # login keeps working. models.py's own `pin_required` CHECK forbids a NULL
        # pin_hash for auth_type='local_pin' (see ## Contract objections in the handoff),
        # so we hash an unguessable, never-issued placeholder and use pin_set_at IS NULL
        # -- not pin_hash IS NULL -- as the "PIN not yet issued by IT" signal that the
        # admin UI and routers/people.py both check.
        placeholder = f"{secrets.randbelow(1_000_000):06d}"
        user = User(employee_id=emp.id, auth_type="local_pin", pin_hash=hash_pin(placeholder))
        db.add(user)

    for r, field_diff in diff.changed:
        emp = db.scalar(select(Employee).where(Employee.employee_code == r.employee_code))
        for f in field_diff:
            setattr(emp, f, getattr(r, f))


def resolve_managers(db: OrmSession) -> tuple[list[str], list[str]]:
    """Second pass: guess `manager_id` from division + band for employees that still lack
    one. Returns (resolved_codes, unresolved_report_lines). Never overwrites a manager_id
    that is already set — a human may have corrected it."""
    employees = list(db.scalars(select(Employee)))
    by_division: dict[str, list[Employee]] = {}
    for e in employees:
        by_division.setdefault(e.division, []).append(e)

    resolved, unresolved = [], []
    for e in employees:
        if e.manager_id is not None:
            continue
        rank = BAND_RANK.get(e.band)
        if rank is None:
            unresolved.append(f"{e.employee_code} ({e.full_name}): unknown band {e.band!r}")
            continue
        candidates = [
            c for c in by_division.get(e.division, [])
            if c.id != e.id and BAND_RANK.get(c.band, -1) > rank
        ]
        if not candidates:
            unresolved.append(
                f"{e.employee_code} ({e.full_name}): no higher band in {e.division!r} - top of that division's ladder"
            )
            continue
        min_rank = min(BAND_RANK[c.band] for c in candidates)
        top = [c for c in candidates if BAND_RANK[c.band] == min_rank]
        if len(top) != 1:
            names = ", ".join(f"{c.employee_code} ({c.band})" for c in top)
            unresolved.append(f"{e.employee_code} ({e.full_name}): ambiguous - {len(top)} candidates at the same band: {names}")
            continue
        e.manager_id = top[0].id
        resolved.append(f"{e.employee_code} -> {top[0].employee_code}")
    return resolved, unresolved


# ── service registry + platform admin ──────────────────────────────────────
# Real Coolify deployment URLs (read from the Coolify API 25 Aug 2026). These are sslip.io
# addresses that will change once real DNS lands, so every one is overridable by an env var
# rather than baked into the dict literals below -- swap the env var when DNS lands, no code
# change needed.
ITEMCODE_URL = os.environ.get(
    "MMOS_SVC_ITEMCODE_URL", "https://2cuflhtkwq2sqxr6swhxafcc.200.234.36.153.sslip.io"
)
ATT_URL = os.environ.get(
    "MMOS_SVC_ATT_URL", "http://llv4ukunkpxp6zhwsqwnyevr.200.234.36.153.sslip.io"
)
OCR_URL = os.environ.get(
    "MMOS_SVC_OCR_URL", "http://tztgni1vqexwngopwpaxwpgh.200.234.36.153.sslip.io"
)
PURCHASE_URL = os.environ.get(
    "MMOS_SVC_PURCHASE_URL", "http://mdqtimbvyv6zwpkgfvmcj44h.200.234.36.153.sslip.io"
)
# Not deployed yet -- built (see handoff/a3-shell.md "Service Desk is a launch shortcut"), no
# container exists on Coolify. Kept as a placeholder row, marked inactive so it never appears
# as a live tile until someone actually deploys it and flips is_active.
SERVICEDESK_URL = os.environ.get(
    "MMOS_SVC_SERVICEDESK_URL", "https://servicedesk.m-mines.com"
)
ERPNEXT_URL = os.environ.get(
    "MMOS_SVC_ERPNEXT_URL", "https://minimines-uat.m.frappe.cloud"
)
TWENTY_URL = os.environ.get("MMOS_SVC_TWENTY_URL", "https://twenty.m-mines.com")

# Each role tuple is (key, name, description). `description` is shown inline on the Access
# page (brand/UI-DECISIONS.md "Access page - four capabilities": "role meanings shown
# inline"); third-party services keep their own sign-in and access model, so their roles here
# are for MM OS's own grant bookkeeping only and don't need a description.
SERVICES: list[dict] = [
    dict(
        slug="erpnext", name="ERPNext", category="erp",
        base_url=ERPNEXT_URL, launch_mode="external",
        roles=[("user", "User", None), ("manager", "Manager", None)],
    ),
    dict(
        slug="itemcode", name="Item Code Studio", category="production",
        base_url=ITEMCODE_URL, launch_mode="handoff",
        has_public_surface=True,
        roles=[
            ("viewer", "Viewer", "Look up and browse item codes inside MM OS."),
            ("admin", "Administrator", "Everything a viewer can do, plus create and edit item codes."),
        ],
    ),
    dict(
        slug="att", name="ATT Platform", category="production",
        base_url=ATT_URL, launch_mode="handoff",
        roles=[
            ("viewer", "Viewer", "Read-only: dashboards, rankings, raw trade data, "
             "geo/regulatory logs, exports, and submitting trader feedback."),
            ("admin", "Administrator", "Everything a viewer can do, plus start, rename and "
             "delete runs, upload trade files and base portfolios, edit scoring weights and "
             "settings, and manage the LLM matcher provider/key."),
        ],
    ),
    dict(
        slug="ocr", name="OCR Service", category="production",
        base_url=OCR_URL, launch_mode="handoff",
        roles=[
            ("viewer", "Viewer", "View OCR jobs and extracted results."),
            ("admin", "Administrator", "Everything a viewer can do, plus manage OCR service configuration."),
        ],
    ),
    dict(
        slug="purchase", name="Project Purchase Analytics", category="production",
        base_url=PURCHASE_URL, launch_mode="handoff",
        roles=[
            ("viewer", "Viewer", "View purchase analytics dashboards and reports."),
            ("admin", "Administrator", "Everything a viewer can do, plus manage data sources and configuration."),
        ],
    ),
    dict(
        slug="servicedesk", name="Service Desk", category="platform",
        base_url=SERVICEDESK_URL, launch_mode="handoff", is_active=False,
        roles=[
            ("requester", "Requester", "Raise requests and track My requests."),
            ("agent", "Agent", "Work the IT agent console: triage, assign, propose and "
             "resolve requests across the department queue."),
            ("admin", "Administrator", "Everything an agent can do, plus approver decisions "
             "and Service Desk administration."),
        ],
    ),
    dict(
        slug="twenty", name="Twenty CRM", category="commercial",
        base_url=TWENTY_URL, launch_mode="external",
        roles=[("user", "User", None)],
    ),
]


def seed_services(db: OrmSession) -> list[str]:
    """Idempotent: only creates slugs that don't already exist. Never updates or deletes an
    existing row, so a base_url (or anything else) an admin has since hand-edited is never
    clobbered by re-running this. Returns created slugs."""
    existing = {s.slug for s in db.scalars(select(Service))}
    created = []
    for spec in SERVICES:
        if spec["slug"] in existing:
            continue
        spec = dict(spec)  # don't mutate the module-level SERVICES list across runs
        roles = spec.pop("roles")
        svc = Service(**spec)
        db.add(svc)
        db.flush()
        for key, name, description in roles:
            db.add(ServiceRole(service_id=svc.id, key=key, name=name, description=description))
        created.append(spec["slug"])
    return created


def seed_platform_admin(db: OrmSession) -> str:
    """Idempotent. Returns a one-line status string."""
    user = db.scalar(select(User).where(User.login_email == PLATFORM_ADMIN_EMAIL))
    if user is not None:
        if not user.is_platform_admin:
            user.is_platform_admin = True
            return f"{PLATFORM_ADMIN_EMAIL}: promoted existing user to platform admin"
        return f"{PLATFORM_ADMIN_EMAIL}: already a platform admin"

    emp = db.scalar(select(Employee).where(Employee.work_email == PLATFORM_ADMIN_EMAIL))
    if emp is None:
        emp = Employee(
            employee_code="MM-ITADMIN",
            full_name="IT Administrator",
            work_email=PLATFORM_ADMIN_EMAIL,
            hr_department="Information Technology",
            division="Corporate",
            job_title="Platform Administrator",
            band="L3",
        )
        db.add(emp)
        db.flush()
    db.add(User(employee_id=emp.id, auth_type="google", login_email=PLATFORM_ADMIN_EMAIL, is_platform_admin=True))
    return f"{PLATFORM_ADMIN_EMAIL}: created as platform admin"


# ── demo batch (batched access rollout) ─────────────────────────────────────────────────
# Chat-instructed for the 25 Aug 2026 demo, layered on top of everything above: seed only a
# curated slice of the sheet -- 2-3 of the most senior people per department, ~20-25 people
# total across ~8-9 departments -- rather than the full-sheet import `apply_diff` does for
# routers/people.py's admin upload. Everyone else in the sheet is simply not seeded yet;
# that is the truthful state of a batched access rollout, not an omission.
#
# Everything below is new, additive code built ON TOP of `load_sheet_rows` / `compute_diff`
# / `apply_diff` / `resolve_managers` -- none of those four functions, or their full-sheet
# behaviour for the admin-UI import path, are touched.
#
# Two ways to run this:
#   --seed-demo   dev machine, reads the real spreadsheet, WIPES existing people first.
#   --demo        no spreadsheet, no arguments -- seeds from the committed fixture
#                 `app/demo_seed.py` (see `dump_demo_fixture` for how that file is made).
#                 Never wipes; safe to run on every container boot.

# Approval-level text, as it actually appears in the sheet, ranked for "how senior is this
# person's sign-off authority." Used to pick the demo approver and to check whether a
# candidate already qualifies as an approver the same way
# servicedesk/app/org_chart.py's qualifies() does: a real tier, not "Operational" or None.
APPROVAL_RANK = {
    None: -1,
    "Operational": 0,
    "L1 (Associate)": 1,
    "L1J": 1,
    "L1S": 1,
    "L2": 2,
    "L2 (Sr Asst Mgr)": 2,
    "L3 (HOD)": 3,
    "L4 (Div Head)": 4,
    "Oversight": 4,
    "L5 (Apex)": 5,
}


def _approval_rank(level: str | None) -> int:
    return APPROVAL_RANK.get(level, 0)


def _qualifies_as_approver(is_approver: bool, approval_level: str | None) -> bool:
    """Mirrors servicedesk/app/org_chart.py's `qualifies()`: an override flag, or a real
    approval tier other than the "no authority" Operational default."""
    return bool(is_approver) or bool(approval_level and approval_level != "Operational")


def select_demo_batch(rows: list[EmployeeRow], *, target_depts: int = 9) -> list[EmployeeRow]:
    """2-3 of the most senior people (by band, then approval level) from each of the
    biggest ~9 departments -- ~20-25 people total, not all 73. Departments with fewer than
    2 rows are skipped entirely: a "who's senior in this department" slice needs more than
    one person to be meaningful, and the owner only asked for roughly 8-9 departments."""
    by_dept: dict[str, list[EmployeeRow]] = {}
    for r in rows:
        by_dept.setdefault(r.hr_department, []).append(r)

    eligible = [d for d, rs in by_dept.items() if len(rs) >= 2]
    eligible.sort(key=lambda d: len(by_dept[d]), reverse=True)
    chosen_depts = eligible[:target_depts]

    def seniority(r: EmployeeRow) -> tuple[int, int]:
        return (BAND_RANK.get(r.band, -1), _approval_rank(r.approval_level))

    selected: list[EmployeeRow] = []
    for d in chosen_depts:
        ranked = sorted(by_dept[d], key=seniority, reverse=True)
        take = 3 if len(ranked) >= 5 else 2
        selected.extend(ranked[:take])
    return selected


def _pick_demo_roles(selected: list[EmployeeRow]) -> dict[str, EmployeeRow]:
    """Pick which four of the selected batch play the non-admin demo-login roles --
    entirely by rank within whatever the sheet currently contains, never by hardcoding a
    real employee's name or code. Returns
    {"approver", "agent", "requester_1", "requester_2"} -> EmployeeRow."""
    by_dept: dict[str, list[EmployeeRow]] = {}
    for r in selected:
        by_dept.setdefault(r.hr_department, []).append(r)

    def seniority(r: EmployeeRow) -> tuple[int, int]:
        return (_approval_rank(r.approval_level), BAND_RANK.get(r.band, -1))

    # Approver: the most senior person who already qualifies as an approver (per
    # servicedesk's own rule) and has at least one other selected colleague in the same
    # department, so the demo can show requester and approver in the same department.
    qualifying = [
        r for r in selected
        if _qualifies_as_approver(r.is_approver, r.approval_level) and len(by_dept[r.hr_department]) >= 2
    ]
    pool = qualifying or [r for r in selected if len(by_dept[r.hr_department]) >= 2] or list(selected)
    approver = sorted(pool, key=seniority, reverse=True)[0]

    # Requester #1: approver's most junior department-mate who does NOT already qualify as
    # an approver -- otherwise the live demo would "approve" one hop too early, before the
    # requester's manager chain even reaches the approver.
    dept_mates = [r for r in selected if r is not approver and r.hr_department == approver.hr_department]
    non_qualifying = [r for r in dept_mates if not _qualifies_as_approver(r.is_approver, r.approval_level)]
    requester_1 = sorted(non_qualifying or dept_mates, key=seniority)[0]

    remaining = [r for r in selected if r is not approver and r is not requester_1]

    # Requester #2: the most senior remaining person from a different department.
    other_dept = [r for r in remaining if r.hr_department != approver.hr_department]
    requester_2 = sorted(other_dept or remaining, key=seniority, reverse=True)[0]
    remaining = [r for r in remaining if r is not requester_2]

    # IT agent: most senior of what's left, preferring a third department so the demo
    # spans four departments across its five logins.
    used_depts = {approver.hr_department, requester_2.hr_department}
    agent_pool = [r for r in remaining if r.hr_department not in used_depts] or remaining
    agent = sorted(agent_pool, key=seniority, reverse=True)[0]

    return {"approver": approver, "agent": agent, "requester_1": requester_1, "requester_2": requester_2}


def resolve_manager_codes(rows: list[EmployeeRow]) -> dict[str, str]:
    """The same heuristic as `resolve_managers` (division + "next band up"), but pure and
    code-keyed: no database, no Employee objects, just `EmployeeRow`s. Used only to compute
    the manager relationships baked into the committed demo fixture -- run against the
    FULL sheet, not just the curated demo subset, so the ranking reflects who is actually
    next-band-up in the real org rather than an artifact of who happened to get selected
    for the demo. Ties and gaps are left unresolved, same as `resolve_managers`. Deliberately
    a separate, small implementation rather than a refactor of `resolve_managers` itself,
    which is shared with routers/people.py and works over live ORM rows, not sheet rows."""
    by_division: dict[str, list[EmployeeRow]] = {}
    for r in rows:
        by_division.setdefault(r.division, []).append(r)

    resolved: dict[str, str] = {}
    for r in rows:
        rank = BAND_RANK.get(r.band)
        if rank is None:
            continue
        candidates = [
            c for c in by_division.get(r.division, [])
            if c.employee_code != r.employee_code and BAND_RANK.get(c.band, -1) > rank
        ]
        if not candidates:
            continue
        min_rank = min(BAND_RANK[c.band] for c in candidates)
        top = [c for c in candidates if BAND_RANK[c.band] == min_rank]
        if len(top) == 1:
            resolved[r.employee_code] = top[0].employee_code
    return resolved


# ── demo batch: destructive reset (explicit and guarded, dev machine only) ──────────────
def clear_all_people(db: OrmSession, *, force: bool = False) -> int:
    """DESTRUCTIVE. Deletes every Employee row, which cascades (via the FKs declared in
    models.py) to every User, Session and Grant. Only ever call this to wipe a throwaway
    demo database before reseeding the curated batch from scratch -- the owner explicitly
    wants the previous demo set removed and replaced, not merged with.

    Not wired into any --commit flag by accident: it only runs when a caller asks for it by
    name (the `--seed-demo` CLI path, or calling this function directly), and it refuses
    outright if `audit_log` already has rows, unless `force=True`. A nonempty audit log
    means real logins or admin actions happened against this database -- at that point it
    is no longer a fresh demo database, and silently wiping identities out from under that
    history would orphan it instead of loudly refusing."""
    audit_rows = db.scalar(select(func.count()).select_from(AuditLog))
    if audit_rows and not force:
        raise RuntimeError(
            f"refusing to wipe employees/users/grants: audit_log already has {audit_rows} "
            "row(s), which looks like real activity rather than an empty demo database. "
            "Re-run with force=True (CLI: --force-wipe) only if you are certain this is "
            "still the throwaway demo instance."
        )
    n = db.scalar(select(func.count()).select_from(Employee)) or 0
    print(f"WIPING {n} employee row(s) (and their users/sessions/grants, by cascade) "
          "before reseeding the demo batch.")
    db.execute(delete(Employee))
    return n


# ── demo batch: five known-PIN logins + grants (shared by both seeding paths) ───────────
DEMO_PIN = "1234"  # Same PIN for all five demo logins -- easy to type live, and the
# employee code already tells the accounts apart. A demo credential on a throwaway
# instance, not a production secret.

# hr_department -> one production service slug it plausibly touches, purely so the demo
# Access page shows a believable, uneven spread instead of either nothing or everything.
# Not derived from any real access policy -- there isn't one yet; the real policy lives in
# the "ERP-Based System Access" prose column that apply_diff already reports instead of
# importing (see ImportDiff.proposed_grants).
DEMO_DEPT_SERVICE_HINTS: dict[str, str] = {
    "N-Hub": "itemcode", "P-Hub": "itemcode", "P-Spoke": "itemcode", "Second Life": "itemcode",
    "Projects": "purchase", "Project": "purchase", "Material Management": "purchase",
    "QA/QC": "ocr",
    "Business Development": "att", "StratOps": "att", "Strategy Operations": "att",
}
DEFAULT_DEMO_SERVICE = "itemcode"

ROLE_ORDER = ("agent", "approver", "requester_1", "requester_2")
ROLE_LABELS = {
    "agent": "IT agent (Service Desk)",
    "approver": "approver",
    "requester_1": "requester",
    "requester_2": "requester",
}
# Extra service grants per role, beyond whatever role_grants below assigns. `None` in the
# slug position means "use this person's department hint".
ROLE_GRANTS: dict[str, list[tuple[str | None, str]]] = {
    "agent": [("servicedesk", "agent"), ("ocr", "viewer")],
    "approver": [("servicedesk", "requester"), (None, "viewer"), ("purchase", "viewer")],
    "requester_1": [("servicedesk", "requester")],
    "requester_2": [("servicedesk", "requester"), (None, "viewer")],
}


@dataclass
class DemoLogin:
    employee_code: str
    full_name: str
    hr_department: str
    role: str
    pin: str


def _dept_service_hint(hr_department: str) -> str:
    return DEMO_DEPT_SERVICE_HINTS.get(hr_department, DEFAULT_DEMO_SERVICE)


def _set_demo_pin(user: User, pin: str) -> None:
    user.pin_hash = hash_pin(pin)
    user.pin_set_at = datetime.now(timezone.utc)
    user.failed_pin_attempts = 0
    user.locked_until = None


def _ensure_grant(db: OrmSession, user: User, slug: str, key: str, *, granted_by=None, reason: str | None = None) -> None:
    """Idempotent: does nothing if this user already has ANY grant on this service --
    models.py's uq_grant_user_service allows only one role per user per service, and a
    re-run must never crash on that, nor silently change a role a demo presenter may have
    hand-adjusted in between runs."""
    service = db.scalar(select(Service).where(Service.slug == slug))
    if service is None:
        raise RuntimeError(f"service {slug!r} not found -- run seed_services() first")
    existing = db.scalar(select(Grant).where(Grant.user_id == user.id, Grant.service_id == service.id))
    if existing is not None:
        return
    role = db.scalar(select(ServiceRole).where(ServiceRole.service_id == service.id, ServiceRole.key == key))
    if role is None:
        raise RuntimeError(f"service role {slug}/{key} not found -- run seed_services() first")
    db.add(Grant(user_id=user.id, service_id=service.id, service_role_id=role.id, granted_by=granted_by, reason=reason))


def apply_demo_logins_and_grants(
    db: OrmSession,
    *,
    role_codes: dict[str, str],
    people_by_code: dict[str, tuple[str, str]],
) -> list[DemoLogin]:
    """The piece shared by both demo-seeding paths (live spreadsheet and committed
    fixture), once the Employee/User rows already exist: seed the service registry, give
    five accounts a known PIN, grant everyone else a light and deliberately uneven spread
    of service access so the shell (and the admin's Access page) shows real tiles instead
    of an empty list, and hand back what to print. Never deletes anything -- grants are
    additive and idempotent (see `_ensure_grant`)."""
    seed_services(db)
    db.flush()

    admin_status = seed_platform_admin(db)
    db.flush()
    admin_user = db.scalar(select(User).where(User.login_email == PLATFORM_ADMIN_EMAIL))
    _set_demo_pin(admin_user, DEMO_PIN)
    print(f"platform admin: {admin_status}")

    logins: list[DemoLogin] = [
        DemoLogin(
            admin_user.employee.employee_code, admin_user.employee.full_name,
            admin_user.employee.hr_department, "platform admin", DEMO_PIN,
        )
    ]
    for slug, key in (("itemcode", "admin"), ("att", "admin"), ("ocr", "admin"), ("purchase", "admin"), ("servicedesk", "admin")):
        _ensure_grant(db, admin_user, slug, key, granted_by=admin_user.id, reason="demo: platform admin sees everything")

    def _user_for(code: str) -> User:
        u = db.scalar(select(User).join(Employee, User.employee_id == Employee.id).where(Employee.employee_code == code))
        if u is None:
            raise RuntimeError(f"demo role points at employee_code {code!r}, which was not seeded")
        return u

    for role in ROLE_ORDER:
        code = role_codes[role]
        user = _user_for(code)
        _set_demo_pin(user, DEMO_PIN)
        full_name, hr_department = people_by_code[code]
        hint_slug = _dept_service_hint(hr_department)
        for slug, key in ROLE_GRANTS[role]:
            _ensure_grant(db, user, slug or hint_slug, key, granted_by=admin_user.id, reason=f"demo: {role}")
        logins.append(DemoLogin(code, full_name, hr_department, ROLE_LABELS[role], DEMO_PIN))

    demo_codes = set(role_codes.values()) | {admin_user.employee.employee_code}
    for code, (full_name, hr_department) in people_by_code.items():
        if code in demo_codes:
            continue
        user = db.scalar(select(User).join(Employee, User.employee_id == Employee.id).where(Employee.employee_code == code))
        if user is None:
            continue
        _ensure_grant(db, user, _dept_service_hint(hr_department), "viewer", granted_by=admin_user.id, reason="demo: department default access")

    return logins


def _print_demo_logins(logins: list[DemoLogin]) -> None:
    print("\n" + "=" * 78)
    print("DEMO LOGINS -- employee code + PIN (sign in at /login)")
    print("=" * 78)
    for l in logins:
        print(f"  {l.employee_code:<12} {l.full_name:<28} {l.hr_department:<24} {l.role:<24} PIN {l.pin}")
    print("=" * 78)


# ── demo batch: spreadsheet-driven path (dev machine, real .xlsx required) ──────────────
def seed_demo_batch(db: OrmSession, xlsx_path: str | Path = DEFAULT_XLSX_PATH, *, force_wipe: bool = False) -> list[DemoLogin]:
    """Dev-machine path: read the real spreadsheet, WIPE the existing employees/users/
    grants (see `clear_all_people`), and reseed the curated ~20-25 person batch plus the
    five demo logins. This is also what `--dump-demo-fixture` runs the selection half of,
    to produce the committed fixture `app/demo_seed.py` for the spreadsheet-less
    container (see `dump_demo_fixture` / `seed_from_fixture`)."""
    rows = load_sheet_rows(xlsx_path)
    selected = select_demo_batch(rows)
    roles = _pick_demo_roles(selected)

    clear_all_people(db, force=force_wipe)
    db.commit()

    diff = compute_diff(db, selected)
    apply_diff(db, diff)
    db.flush()

    # Wire the demo approver <-> requester_1 relationship explicitly. This is asserted for
    # the live demo, not derived: the org is genuinely flat (A1's handoff found only 11 of
    # 73 real managers resolve at all) and `resolve_managers`' division-wide heuristic,
    # run below for everyone else, has no reason to land on exactly this pair out of a
    # whole division. Without this, "an automation request can be approved live" would
    # depend on which way a tie-break heuristic happened to fall.
    approver_emp = db.scalar(select(Employee).where(Employee.employee_code == roles["approver"].employee_code))
    requester1_emp = db.scalar(select(Employee).where(Employee.employee_code == roles["requester_1"].employee_code))
    requester1_emp.manager_id = approver_emp.id
    db.flush()

    resolved, unresolved = resolve_managers(db)
    db.commit()
    print(f"manager_id resolved for {len(resolved)} more employee(s), "
          f"{len(unresolved)} left unresolved (reported, not guessed).")

    role_codes = {k: v.employee_code for k, v in roles.items()}
    people_by_code = {r.employee_code: (r.full_name, r.hr_department) for r in selected}

    logins = apply_demo_logins_and_grants(db, role_codes=role_codes, people_by_code=people_by_code)
    db.commit()
    return logins


def dump_demo_fixture(xlsx_path: str | Path = DEFAULT_XLSX_PATH) -> str:
    """Render `app/demo_seed.py`'s content from the live spreadsheet. The selection logic
    above (`select_demo_batch`, `_pick_demo_roles`) stays the single source of truth; this
    only serializes its output as literal Python so a spreadsheet-less container can seed
    itself. Deliberately excludes every email address -- see the header this generates for
    why. Re-run `--dump-demo-fixture` and overwrite the file whenever the sheet, or the
    selection logic, changes; never hand-edit the generated DEMO_PEOPLE list."""
    rows = load_sheet_rows(xlsx_path)
    all_manager_codes = resolve_manager_codes(rows)
    selected = select_demo_batch(rows)
    roles = _pick_demo_roles(selected)
    selected_codes = {r.employee_code for r in selected}

    # Same explicit override as seed_demo_batch, so the fixture and the live spreadsheet
    # path produce an identical org shape for the demo.
    forced_manager = {roles["requester_1"].employee_code: roles["approver"].employee_code}

    header = f'''"""Real MiniMines employee names for a demo -- see backend/app/seed.py's
"dump_demo_fixture" for how this file is produced and "seed_from_fixture" for how it is
consumed.

The Coolify container cannot reach Employee_Role_Access_Mapping.xlsx (it lives outside the
repo on purpose -- it holds every employee's personal contact detail), so this file is a
snapshot the container seeds itself from with no spreadsheet present.

Contains REAL employee full names, for a demo, in a private repo. Deliberately excludes
every email address: PIN login needs none, and 49 of the sheet's 73 "Work Email" values are
personal gmail.com addresses that must never enter git or an internet-facing box. The one
exception is the platform admin's "{PLATFORM_ADMIN_EMAIL}", a role address, not a person --
seed_platform_admin() creates that one the same way it always has; it is not repeated here.

DELETE THIS FILE once the real batched rollout (reading the spreadsheet directly, from a
box that can reach it) replaces it.

Generated by `python -m app.seed --dump-demo-fixture`, from select_demo_batch() /
_pick_demo_roles() in app/seed.py, against the real spreadsheet. Re-run that command to
regenerate after the sheet changes -- do not hand-edit DEMO_PEOPLE or DEMO_LOGIN_ROLES.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoPerson:
    employee_code: str
    full_name: str
    hr_department: str
    division: str
    job_title: str
    band: str
    approval_level: str | None
    manager_employee_code: str | None


DEMO_PEOPLE: list[DemoPerson] = ['''

    lines = [header]
    for r in selected:
        mgr = forced_manager.get(r.employee_code) or all_manager_codes.get(r.employee_code)
        if mgr not in selected_codes:
            mgr = None
        lines.append(
            "    DemoPerson("
            f"{r.employee_code!r}, {r.full_name!r}, {r.hr_department!r}, {r.division!r}, "
            f"{r.job_title!r}, {r.band!r}, {r.approval_level!r}, {mgr!r}),"
        )
    lines.append("]")
    lines.append("")
    lines.append("# Which of the above play the four non-admin demo logins (the platform admin is")
    lines.append("# synthetic and always seeded by seed_platform_admin(), not listed here).")
    lines.append("DEMO_LOGIN_ROLES: dict[str, str] = {")
    for role in ROLE_ORDER:
        lines.append(f"    {role!r}: {roles[role].employee_code!r},")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


# ── demo batch: fixture-driven path (container boot, no spreadsheet, no arguments) ──────
def seed_from_fixture(db: OrmSession) -> list[DemoLogin]:
    """Container-boot path: no spreadsheet, no network, no --xlsx. Seeds from the literal
    data committed in `app/demo_seed.py` (see that module's docstring, and
    `dump_demo_fixture` above for how it is produced). Reuses the exact same
    `compute_diff`/`apply_diff` the admin-UI import path uses, so it is additive and
    idempotent -- safe to run on every container start, and it never wipes anything by
    itself (unlike `seed_demo_batch`'s dev-machine path)."""
    from . import demo_seed  # local import: this module only exists once generated/committed

    rows = [
        EmployeeRow(
            employee_code=p.employee_code, full_name=p.full_name, work_email=None,
            hr_department=p.hr_department, division=p.division, job_title=p.job_title,
            band=p.band, approval_level=p.approval_level, is_approver=False, notes=None,
            erp_access_text=None, extra_access_text=None,
        )
        for p in demo_seed.DEMO_PEOPLE
    ]

    diff = compute_diff(db, rows)
    apply_diff(db, diff)
    db.flush()
    print(f"fixture: {len(diff.new)} new, {len(diff.changed)} changed, "
          f"{len(rows) - len(diff.new) - len(diff.changed)} unchanged")

    for p in demo_seed.DEMO_PEOPLE:
        if not p.manager_employee_code:
            continue
        emp = db.scalar(select(Employee).where(Employee.employee_code == p.employee_code))
        if emp is None or emp.manager_id is not None:
            continue  # never overwrite a manager_id a human may have corrected
        manager_emp = db.scalar(select(Employee).where(Employee.employee_code == p.manager_employee_code))
        if manager_emp is not None:
            emp.manager_id = manager_emp.id
    db.commit()

    people_by_code = {p.employee_code: (p.full_name, p.hr_department) for p in demo_seed.DEMO_PEOPLE}
    logins = apply_demo_logins_and_grants(db, role_codes=dict(demo_seed.DEMO_LOGIN_ROLES), people_by_code=people_by_code)
    db.commit()
    return logins


# ── CLI ──────────────────────────────────────────────────────────────────────
def _print_diff(diff: ImportDiff) -> None:
    print(f"new:         {len(diff.new)}")
    for r in diff.new:
        print(f"  + {r.employee_code}  {r.full_name}  ({r.hr_department})")
    print(f"changed:     {len(diff.changed)}")
    for r, fd in diff.changed:
        print(f"  ~ {r.employee_code}  {r.full_name}")
        for f, (old, new) in fd.items():
            print(f"      {f}: {old!r} -> {new!r}")
    print(f"missing:     {len(diff.missing_codes)}  (in database, not in this sheet - not touched)")
    for code in diff.missing_codes:
        print(f"  ? {code}")
    print(f"conflicting: {len(diff.conflicts)}  (skipped, not written)")
    for c in diff.conflicts:
        print(f"  ! {c}")
    print()
    print(f"proposed grants report ({len(diff.proposed_grants)} employees have prose access notes"
          " - NOT imported as grants, for a human to tick in the admin UI):")
    for code, name, text in diff.proposed_grants:
        print(f"  * {code} {name}: {text}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import the employee/role/access spreadsheet.")
    parser.add_argument("--xlsx", default=str(DEFAULT_XLSX_PATH), help="Path to the .xlsx source")
    parser.add_argument("--commit", action="store_true", help="Apply the diff. Default is dry-run.")
    parser.add_argument(
        "--seed-demo", action="store_true",
        help="Dev machine only: read --xlsx, WIPE existing employees/users/grants, and reseed "
             "the curated ~20-25 person demo batch plus the five demo logins. Dry-run unless "
             "--commit is also given.",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Seed from the committed fixture app/demo_seed.py -- no spreadsheet, no other "
             "arguments needed. Additive and idempotent; never wipes. Safe on every container boot.",
    )
    parser.add_argument(
        "--dump-demo-fixture", action="store_true",
        help="Dev machine only: read --xlsx and (over)write app/demo_seed.py from the current "
             "selection, for --demo to use on a box with no spreadsheet.",
    )
    parser.add_argument(
        "--force-wipe", action="store_true",
        help="With --seed-demo --commit: wipe even if audit_log already has rows. Dangerous -- "
             "only for a throwaway demo database that has seen real logins/admin actions.",
    )
    args = parser.parse_args(argv)

    if args.dump_demo_fixture:
        content = dump_demo_fixture(args.xlsx)
        out_path = Path(__file__).parent / "demo_seed.py"
        out_path.write_text(content, encoding="utf-8")
        print(f"Wrote {out_path} ({len(content)} bytes, {content.count('DemoPerson(')} people). "
              "Review it, then commit it -- this is the file the spreadsheet-less container seeds from.")
        return 0

    if args.demo:
        db = SessionLocal()
        try:
            logins = seed_from_fixture(db)
            _print_demo_logins(logins)
            print("\nCommitted.")
        finally:
            db.close()
        return 0

    if args.seed_demo:
        rows = load_sheet_rows(args.xlsx)
        selected = select_demo_batch(rows)
        depts = sorted({r.hr_department for r in selected})
        print(f"Read {len(rows)} data row(s) from {args.xlsx!r}. "
              f"Demo batch: {len(selected)} people across {len(depts)} department(s): {', '.join(depts)}.\n")

        if not args.commit:
            print("Dry run - nothing written (and nothing wiped). Re-run with --commit to apply.")
            return 0

        db = SessionLocal()
        try:
            logins = seed_demo_batch(db, args.xlsx, force_wipe=args.force_wipe)
            _print_demo_logins(logins)
            print("\nCommitted.")
        finally:
            db.close()
        return 0

    rows = load_sheet_rows(args.xlsx)
    print(f"Read {len(rows)} data row(s) from {args.xlsx!r}, sheet {SHEET_NAME!r}.\n")

    db = SessionLocal()
    try:
        diff = compute_diff(db, rows)
        _print_diff(diff)

        if not args.commit:
            print("\nDry run - nothing written. Re-run with --commit to apply.")
            return 0

        apply_diff(db, diff)
        db.commit()

        resolved, unresolved = resolve_managers(db)
        db.commit()
        print(f"\nmanager_id resolved for {len(resolved)} employee(s):")
        for line in resolved:
            print(f"  {line}")
        print(f"manager_id left unresolved for {len(unresolved)} employee(s) (reported, not guessed):")
        for line in unresolved:
            print(f"  {line}")

        created_services = seed_services(db)
        admin_status = seed_platform_admin(db)
        db.commit()
        print(f"\nservice registry: created {created_services or 'nothing new'}")
        print(f"platform admin: {admin_status}")

        print("\nCommitted.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
