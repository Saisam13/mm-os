"""Tests for scripts/provision_functional.py -- the roster-driven loader that creates MM OS
accounts for FUNCTIONAL MAILBOXES (department mailboxes, not personal names). Only synthetic
data appears here -- fake employee codes and *@example.test addresses, never the real roster
or a real name/email.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select

# scripts/ lives at the repo root, one level above backend/ -- put the repo root on sys.path
# so `import scripts.provision_functional` resolves regardless of how pytest was invoked.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.provision_functional import load_roster, process_row  # noqa: E402

from app.models import Employee, User  # noqa: E402
from app.provision import must_change_pin  # noqa: E402

ROSTER_HEADER = "employee_code,login_email,department,role,approval_level,platform_admin\n"


def _write_roster(tmp_path, body: str) -> Path:
    path = tmp_path / "roster.csv"
    path.write_text(ROSTER_HEADER + body, encoding="utf-8")
    return path


# ── CSV parsing: blank columns really mean unset ────────────────────────────────────────
def test_load_roster_parses_blank_fields_as_unset(tmp_path):
    path = _write_roster(
        tmp_path,
        "FN01,purchase.c2@example.test,Purchase,requester,,\n"
        "FN02,central.stores@example.test,Central Stores,approver,L3 (HOD),true\n",
    )
    rows = load_roster(path)
    assert len(rows) == 2
    assert rows[0].employee_code == "FN01"
    assert rows[0].approval_level is None
    assert rows[0].platform_admin is False
    assert rows[1].approval_level == "L3 (HOD)"
    assert rows[1].platform_admin is True


# ── dry run writes nothing ──────────────────────────────────────────────────────────────
def test_dry_run_creates_nothing(db, tmp_path):
    path = _write_roster(tmp_path, "FN10,sales@example.test,Sales,requester,,\n")
    row = load_roster(path)[0]

    result = process_row(db, row, commit=False, reset=False, pin_length=6)
    db.rollback()

    assert result.employee_action == "would_create"
    assert result.user_action == "would_create"
    assert result.pin is None
    assert db.scalar(select(Employee).where(Employee.employee_code == "FN10")) is None


# ── --commit creates the account with a must-change one-time PIN ───────────────────────
def test_commit_creates_account_with_must_change_pin(db, tmp_path):
    path = _write_roster(tmp_path, "FN11,central.stores@example.test,Central Stores,requester,,\n")
    row = load_roster(path)[0]

    result = process_row(db, row, commit=True, reset=False, pin_length=6)
    db.commit()

    assert result.employee_action == "created"
    assert result.user_action == "created"
    assert result.pin and result.pin.isdigit() and len(result.pin) == 6

    emp = db.scalar(select(Employee).where(Employee.employee_code == "FN11"))
    assert emp is not None
    assert emp.work_email == "central.stores@example.test"
    assert emp.hr_department == "Central Stores"
    assert emp.full_name == "Central Stores"  # label derived from the mailbox local-part
    assert emp.status == "active"

    user = db.scalar(select(User).where(User.employee_id == emp.id))
    assert user is not None
    assert user.is_platform_admin is False
    assert must_change_pin(db, user) is True


# ── blank approval_level / platform_admin stay unset, never defaulted ──────────────────
def test_blank_approval_level_and_platform_admin_stay_unset(db, tmp_path):
    path = _write_roster(tmp_path, "FN12,sales@example.test,Sales,requester,,\n")
    row = load_roster(path)[0]

    process_row(db, row, commit=True, reset=False, pin_length=6)
    db.commit()

    emp = db.scalar(select(Employee).where(Employee.employee_code == "FN12"))
    user = db.scalar(select(User).where(User.employee_id == emp.id))
    assert emp.approval_level is None
    assert user.is_platform_admin is False


# ── a truthy platform_admin grants admin without tripping no_pin_admins ────────────────
def test_truthy_platform_admin_grants_admin_without_tripping_no_pin_admins(db, tmp_path):
    path = _write_roster(
        tmp_path, "FN13,central.stores@example.test,Central Stores,approver,L3 (HOD),yes\n"
    )
    row = load_roster(path)[0]

    result = process_row(db, row, commit=True, reset=False, pin_length=6)
    db.commit()

    assert result.platform_admin is True
    emp = db.scalar(select(Employee).where(Employee.employee_code == "FN13"))
    assert emp.approval_level == "L3 (HOD)"  # non-blank column IS written

    user = db.scalar(select(User).where(User.employee_id == emp.id))
    assert user.is_platform_admin is True
    # no_pin_admins (models.py): a platform admin can never be a local_pin user.
    assert user.auth_type == "google"
    assert user.login_email == "central.stores@example.test"
    assert must_change_pin(db, user) is True


# ── re-running is idempotent and never resets an issued PIN without --reset ───────────
def test_rerun_is_idempotent_and_keeps_pin_unless_reset(db, tmp_path):
    path = _write_roster(tmp_path, "FN14,sales@example.test,Sales,requester,,\n")
    row = load_roster(path)[0]

    first = process_row(db, row, commit=True, reset=False, pin_length=6)
    db.commit()
    assert first.pin

    second = process_row(db, row, commit=True, reset=False, pin_length=6)
    db.commit()
    assert second.employee_action == "unchanged"
    assert second.user_action == "pin_kept"
    assert second.pin is None

    employees = db.scalars(select(Employee).where(Employee.employee_code == "FN14")).all()
    assert len(employees) == 1
    users = db.scalars(select(User).where(User.employee_id == employees[0].id)).all()
    assert len(users) == 1

    third = process_row(db, row, commit=True, reset=True, pin_length=6)
    db.commit()
    assert third.user_action == "pin_reset"
    assert third.pin and third.pin != first.pin
