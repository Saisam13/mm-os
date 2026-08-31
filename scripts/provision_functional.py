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

Disabled-by-default note: every account this loader CREATES starts with is_active=False
(User.is_active) -- IT reviews the roster in the admin Accounts page and enables each mailbox
by hand before anyone can sign in with it (see app/deps.py's current_user, which refuses a
sign-in for an inactive user regardless of a valid PIN/session). Pass --active to create
accounts already enabled instead. Re-running is still safe either way: `active` is only ever
applied when a NEW account is created here -- an account that already exists (and that an
admin may have since enabled) is never re-disabled by a later run, with or without --active
(see app/provision.py's _ensure_functional_user).

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

from app.db import SessionLocal  # noqa: E402
from app.provision import (  # noqa: E402
    DEFAULT_FUNCTIONAL_ROLE,
    AccountResult,
    provision_account,
)

# The per-row provisioning core (create/update the Employee + User, issue the one-time PIN,
# honour "blank means leave unset") now lives in app/provision.py so this CLI and the admin
# API endpoint POST /api/admin/accounts share ONE implementation and can never drift. This
# module keeps only the roster-CSV concerns: reading the file and printing the report.
RowResult = AccountResult  # kept as a local alias for the report/CSV writers below

REQUIRED_COLUMNS = ("employee_code", "login_email", "department")
DEFAULT_ROLE = DEFAULT_FUNCTIONAL_ROLE
TRUTHY = {"true", "1", "yes", "y", "t"}


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _truthy(v) -> bool:
    return (_clean(v) or "").lower() in TRUTHY


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


def process_row(
    db, row: RosterRow, *, commit: bool, reset: bool, pin_length: int, active: bool = False
) -> RowResult:
    """Provision one roster row through the shared core (app/provision.provision_account)."""
    return provision_account(
        db,
        employee_code=row.employee_code,
        login_email=row.login_email,
        department=row.department,
        role=row.role,
        approval_level=row.approval_level,
        platform_admin=row.platform_admin,
        active=active,
        commit=commit,
        reset=reset,
        pin_length=pin_length,
    )


def _print_report(results: list[RowResult], *, commit: bool, active: bool) -> None:
    verb = "DID" if commit else "WOULD DO (dry run -- nothing written)"
    print(f"\n{'=' * 78}\n{verb}\n{'=' * 78}")
    state = "ENABLED" if active else "DISABLED (review + enable each in the admin Accounts page)"
    print(f"New accounts are created {state}.")
    for r in results:
        admin_tag = " [platform admin]" if r.platform_admin else ""
        pin_tag = f"  PIN {r.pin}" if r.pin else ""
        new_tag = ""
        if r.employee_action in ("created", "would_create"):
            new_tag = "  [disabled]" if not active else "  [enabled]"
        print(
            f"  {r.employee_code:<14} {r.login_email:<32} employee={r.employee_action:<13} "
            f"user={r.user_action:<12}{admin_tag}{pin_tag}{new_tag}"
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
    parser.add_argument(
        "--active", action="store_true",
        help="Create new accounts already ENABLED. Default: new accounts are created DISABLED "
             "(is_active=False) so IT reviews and enables each one in the admin Accounts page "
             "before anyone can sign in. Never re-enables or re-disables an account that "
             "already exists -- see app/provision.py.",
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
            process_row(
                db, row, commit=args.commit, reset=args.reset, pin_length=args.pin_length,
                active=args.active,
            )
            for row in rows
        ]

        if not args.commit:
            db.rollback()
            _print_report(results, commit=False, active=args.active)
            print("\nDry run -- nothing written, no PIN issued. Re-run with --commit to apply.")
            return 0

        db.commit()
        _print_report(results, commit=True, active=args.active)
        if args.out:
            _write_pins_csv(args.out, results)
            print(f"\nWrote PIN handout to {args.out!r}.")
        print("\nCommitted.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
