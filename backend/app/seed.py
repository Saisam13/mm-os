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
from pathlib import Path
from typing import BinaryIO

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .db import SessionLocal
from .models import Employee, Service, ServiceRole, User
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
    args = parser.parse_args(argv)

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
