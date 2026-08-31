"""Provision MM OS accounts for FUNCTIONAL MAILBOXES from a roster CSV.

MM OS is moving to functional-mailbox accounts rather than personal ones: each department
mailbox (e.g. purchase.c2@m-mines.com, central.stores@m-mines.com, sales@m-mines.com) becomes
one MM OS account, the same way a named employee gets one via
scripts/provision_people.py / app/provision.py. This script is the functional-mailbox
counterpart -- same underlying mechanism (Employee + User + issue_one_time_pin), driven by a
roster file instead of the HR spreadsheet.

    PY = backend/.venv/Scripts/python.exe  (Windows)  |  backend/.venv/bin/python  (Linux VPS)

    # Dry run -- shows what WOULD be created/updated, writes nothing, reveals no PIN:
    PY -m scripts.provision_functional --roster roster.csv

    # Apply -- creates/updates the accounts, issues one-time PINs, and writes a PIN handout:
    PY -m scripts.provision_functional --roster roster.csv --commit --out pins.csv

    # Re-run safely any time -- existing rows are updated in place, never duplicated, and an
    # already-issued PIN is left alone unless you pass --reset:
    PY -m scripts.provision_functional --roster roster.csv --commit --reset

Roster CSV columns (header row required): employee_code, login_email, department, role,
approval_level, platform_admin.

`approval_level` and `platform_admin` are intentionally BLANK for most rows -- the admin sets
heads/approvers later in the admin UI. Blank means "leave unset", never a default:
  - approval_level: only written if the column is non-blank. A blank column never overwrites
    an approval_level a human has since set on that Employee.
  - platform_admin: only truthy values (true/1/yes/y/t, case-insensitive) grant
    is_platform_admin, via the SAME mechanism app/provision.py's provision_by_code uses for
    the no_pin_admins CHECK in app/models.py (a PIN user can never be a platform admin) --
    auth_type is flipped to 'google', login_email is set, and a one-time PIN is still issued.
    Blank means a normal account; it never demotes an existing admin.

Role modeling note (see handoff at the bottom of this docstring): this script does NOT create
any Grant row from the roster's `role` column. app/models.py's Grant is a per-(user, service)
row -- "one person may open one service in one role" -- and the roster has no column saying
WHICH service each mailbox's role applies to (a department name is not a service slug; e.g.
"Purchase" the department is not necessarily the "purchase" service in app/seed.py's SERVICES
list). Guessing that mapping would silently grant the wrong service. Instead the role is
recorded on Employee.notes at creation time as a plain-text reminder, and printed as a TODO
line for the admin to action through the existing POST /api/admin/grants /
POST /api/admin/grants/bulk endpoints (backend/app/routers/platform.py) once they decide which
service each functional mailbox actually needs.

Auth type note: a new account defaults to auth_type='google' with login_email=the roster's
login_email (unlike app/seed.py's apply_diff, which defaults personal-employee imports to
local_pin) -- these mailboxes are real corporate addresses, not shared shop-floor terminals.
Every account still gets a must-change one-time PIN regardless of auth_type: PIN login is
keyed off pin_hash, not auth_type (see app/provision.py / routers/auth.py), so the mailbox
holder can sign in with the PIN on day one and add Google sign-in whenever they choose.

Nothing here reads or embeds the real roster into the repo -- the CSV path is only ever an
argument, never a default.
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

# backend/ on sys.path so `import app...` resolves regardless of invocation directory.
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(_BACKEND))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Employee, User  # noqa: E402
from app.provision import issue_one_time_pin  # noqa: E402

REQUIRED_COLUMNS = ("employee_code", "login_email", "department")
DEFAULT_ROLE = "requester"
TRUTHY = {"true", "1", "yes", "y", "t"}


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _truthy(v) -> bool:
    return (_clean(v) or "").lower() in TRUTHY


def _label_from_email(email: str) -> str:
    """A readable full_name from the mailbox's local-part, e.g. "purchase.c2@m-mines.com"
    -> "Purchase C2". Falls back to the raw local-part if it has no word characters at all."""
    local = email.split("@", 1)[0]
    words = [w for w in local.replace(".", " ").replace("_", " ").replace("-", " ").split() if w]
    return " ".join(w.capitalize() for w in words) or local


@dataclass
class RosterRow:
    employee_code: str
    login_email: str
    department: str
    role: str
    approval_level: str | None
    platform_admin: bool


def load_roster(path: str | Path) -> list[RosterRow]:
    rows: list[RosterRow] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise ValueError(f"Roster CSV is missing required column(s): {missing}")
        for raw in reader:
            code = _clean(raw.get("employee_code"))
            email = _clean(raw.get("login_email"))
            if not code or not email:
                continue  # blank trailing row
            rows.append(
                RosterRow(
                    employee_code=code,
                    login_email=email,
                    department=_clean(raw.get("department")) or "",
                    role=_clean(raw.get("role")) or DEFAULT_ROLE,
                    approval_level=_clean(raw.get("approval_level")),
                    platform_admin=_truthy(raw.get("platform_admin")),
                )
            )
    return rows


@dataclass
class RowResult:
    employee_code: str
    login_email: str
    employee_action: str  # would_create | created | would_update | updated | unchanged
    user_action: str      # would_create | created | pin_kept | pin_reset | admin_no_email
    role: str
    platform_admin: bool
    pin: str | None = None


def _ensure_employee(db, row: RosterRow, *, commit: bool) -> tuple[Employee | None, str]:
    """Idempotent, keyed on employee_code. Never creates a second Employee for a code that
    already exists; updates work_email/hr_department (and the derived label) in place."""
    existing = db.scalar(select(Employee).where(Employee.employee_code == row.employee_code))
    label = _label_from_email(row.login_email)

    if existing is None:
        if not commit:
            return None, "would_create"
        emp = Employee(
            employee_code=row.employee_code,
            full_name=label,
            work_email=row.login_email,
            hr_department=row.department,
            division=row.department or "Functional",
            job_title="Functional Mailbox",
            band="N/A",
            status="active",
            notes=f"functional mailbox; requested role: {row.role} (no Grant created -- see TODO)",
        )
        if row.approval_level:
            emp.approval_level = row.approval_level
        db.add(emp)
        db.flush()  # need emp.id for the User row
        return emp, "created"

    changed = (
        (existing.work_email or None) != (row.login_email or None)
        or (existing.hr_department or None) != (row.department or None)
        or existing.full_name != label
        or (row.approval_level and (existing.approval_level or None) != row.approval_level)
    )
    if not commit:
        return existing, ("would_update" if changed else "unchanged")

    existing.work_email = row.login_email
    existing.hr_department = row.department
    existing.full_name = label
    if row.approval_level:  # blank never overwrites an approval_level already on file
        existing.approval_level = row.approval_level
    return existing, ("updated" if changed else "unchanged")


def _ensure_user(
    db, employee: Employee | None, row: RosterRow, *, commit: bool, reset: bool, pin_length: int
) -> tuple[str, str | None]:
    """Returns (user_action, pin_or_None). Idempotent: re-running never duplicates a User and
    never resets an already-issued PIN unless `reset=True`."""
    user = None
    if employee is not None:
        user = db.scalar(select(User).where(User.employee_id == employee.id))

    if user is None:
        if not commit:
            return "would_create", None
        user = User(employee_id=employee.id, auth_type="google", login_email=row.login_email)
        db.add(user)
        db.flush()
        if row.platform_admin:
            user.is_platform_admin = True  # already auth_type='google' with login_email set
        pin = issue_one_time_pin(db, user, length=pin_length)
        return "created", pin

    # existing user
    if not commit:
        if row.platform_admin and not user.is_platform_admin and not (user.login_email or row.login_email):
            return "would_flag_admin_no_email", None
        already_issued = user.pin_set_at is not None
        return ("would_issue_pin" if (reset or not already_issued) else "unchanged"), None

    if row.platform_admin and not user.is_platform_admin:
        # Same mechanism as app/provision.py's provision_by_code: models.py's no_pin_admins
        # CHECK forbids a local_pin admin, so flip to google auth first.
        email = user.login_email or row.login_email
        if not email:
            return "admin_no_email", None
        user.login_email = email
        user.auth_type = "google"
        user.is_platform_admin = True

    already_issued = user.pin_set_at is not None
    if already_issued and not reset:
        return "pin_kept", None
    pin = issue_one_time_pin(db, user, length=pin_length)
    return ("pin_reset" if already_issued else "pin_issued"), pin


def process_row(db, row: RosterRow, *, commit: bool, reset: bool, pin_length: int) -> RowResult:
    employee, employee_action = _ensure_employee(db, row, commit=commit)
    user_action, pin = _ensure_user(
        db, employee, row, commit=commit, reset=reset, pin_length=pin_length
    )
    platform_admin_applied = bool(
        commit and employee is not None and user_action not in ("admin_no_email",) and row.platform_admin
    )
    return RowResult(
        employee_code=row.employee_code,
        login_email=row.login_email,
        employee_action=employee_action,
        user_action=user_action,
        role=row.role,
        platform_admin=platform_admin_applied if commit else row.platform_admin,
        pin=pin,
    )


def _print_report(results: list[RowResult], *, commit: bool) -> None:
    verb = "DID" if commit else "WOULD DO (dry run -- nothing written)"
    print(f"\n{'=' * 78}\n{verb}\n{'=' * 78}")
    for r in results:
        admin_tag = " [platform admin]" if r.platform_admin else ""
        pin_tag = f"  PIN {r.pin}" if r.pin else ""
        print(
            f"  {r.employee_code:<14} {r.login_email:<32} employee={r.employee_action:<13} "
            f"user={r.user_action:<12}{admin_tag}{pin_tag}"
        )
    print("=" * 78)

    todo_roles = {(r.role) for r in results if r.employee_action in ("created", "would_create")}
    if todo_roles:
        print(
            "\nTODO for the admin: no per-service Grant rows were created for any account "
            "(a department/role in the roster does not say which MM OS service it maps to). "
            "Requested roles were recorded on each new Employee's notes field. Once you decide "
            "the service mapping, grant access via POST /api/admin/grants or "
            "/api/admin/grants/bulk. Roles seen in this roster: " + ", ".join(sorted(todo_roles))
        )


def _write_pins_csv(path: str | Path, results: list[RowResult]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["employee_code", "login_email", "one_time_pin", "platform_admin"])
        for r in results:
            if r.pin:
                writer.writerow([r.employee_code, r.login_email, r.pin, "yes" if r.platform_admin else "no"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--roster", required=True, help="Path to the roster CSV (read in place, never embedded)")
    parser.add_argument("--commit", action="store_true", help="Apply. Default is a dry run that writes nothing and reveals no PIN.")
    parser.add_argument("--out", help="With --commit: write a CSV of employee_code, login_email, one-time PIN, admin? for distributing PINs")
    parser.add_argument("--pin-length", type=int, default=6, help="Length of each generated PIN (4-8, default 6)")
    parser.add_argument(
        "--reset", action="store_true",
        help="Also reissue a one-time PIN for accounts that already have one. Default: an "
             "already-issued PIN is left alone (idempotent re-run).",
    )
    args = parser.parse_args(argv)

    try:
        rows = load_roster(args.roster)
    except (OSError, ValueError) as exc:
        print(f"Could not read roster: {exc}", file=sys.stderr)
        return 2

    print(f"Read {len(rows)} row(s) from {args.roster!r}.")

    db = SessionLocal()
    try:
        results = [
            process_row(db, row, commit=args.commit, reset=args.reset, pin_length=args.pin_length)
            for row in rows
        ]

        if not args.commit:
            db.rollback()
            _print_report(results, commit=False)
            print("\nDry run -- nothing written, no PIN issued. Re-run with --commit to apply.")
            return 0

        db.commit()
        _print_report(results, commit=True)
        if args.out:
            _write_pins_csv(args.out, results)
            print(f"\nWrote PIN handout to {args.out!r}.")
        print("\nCommitted.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
