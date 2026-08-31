"""Real-person provisioning: issue a specific named employee a one-time PIN they must
change on first login.

This is the start of the real rollout that replaces the 23-name demo seed (which is now
opt-in -- see app/seed.py and docs/10-runbook.md). It provisions SPECIFIC people by employee
code, never a whole sheet, so IT can bring real staff online a handful at a time.

"Must change on first login" needs a bit of state the frozen `users` table does not carry, so
it lives in a tiny side table here (`pin_must_change`) rather than by overloading `pin_set_at`
-- that field keeps its existing meaning ("IT has issued a real PIN"), so the admin UI still
reads honestly right after provisioning. Presence of a row = the user is still on their
one-time PIN; the self-service change endpoint (routers/auth.py `POST /api/auth/pin/change`)
deletes it.

Names: the CLI (scripts/provision_people.py) reads the mapping spreadsheet IN PLACE to import
people who are not yet in the database; nothing here writes a name or email into the repo. The
admin endpoint (routers/people.py `POST /api/admin/provision`) works purely on employee codes
against people already imported, so it needs no spreadsheet at all.
"""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session as OrmSession, mapped_column

from .models import Base, Employee, User
from .security import hash_pin

DEFAULT_FUNCTIONAL_ROLE = "requester"
FUNCTIONAL_JOB_TITLE = "Functional Mailbox"


class PinMustChange(Base):
    """One row per user who is still on a provisioned one-time PIN. Deleted when they change
    it. `user_id` is the primary key -- a user is either flagged or not, never twice."""

    __tablename__ = "pin_must_change"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def must_change_pin(db: OrmSession, user: User) -> bool:
    return db.get(PinMustChange, user.id) is not None


def clear_must_change(db: OrmSession, user: User) -> None:
    row = db.get(PinMustChange, user.id)
    if row is not None:
        db.delete(row)


def _set_must_change(db: OrmSession, user: User) -> None:
    if db.get(PinMustChange, user.id) is None:
        db.add(PinMustChange(user_id=user.id))


def generate_pin(length: int = 6) -> str:
    """A numeric PIN of `length` digits (security.hash_pin accepts 4-8). Uniform digits,
    leading zeros allowed -- it is compared as a string, never parsed as an int."""
    length = max(4, min(8, length))
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def issue_one_time_pin(
    db: OrmSession, user: User, *, pin: str | None = None, length: int = 6
) -> str:
    """Set `user`'s PIN to a one-time value and flag it must-change. `pin_set_at` is set to now
    (a real PIN has been issued by IT), and the must-change row is what makes it one-time.
    Returns the raw PIN -- the caller shows it once and never stores it."""
    pin = pin or generate_pin(length)
    user.pin_hash = hash_pin(pin)  # raises ValueError on a bad explicit pin
    user.pin_set_at = datetime.now(timezone.utc)
    user.failed_pin_attempts = 0
    user.locked_until = None
    _set_must_change(db, user)
    return pin


def provision_by_code(
    db: OrmSession,
    employee_code: str,
    *,
    pin: str | None = None,
    length: int = 6,
    platform_admin: bool = False,
) -> tuple[str | None, str]:
    """Provision a one-time PIN for an already-imported employee, by code.

    Returns (pin, status). status is "provisioned" (pin is the raw one-time PIN),
    "no_user" (no MM OS login for that code -- import them first), "inactive", or
    "no_email" (platform_admin was requested but the employee has no work_email to
    authenticate as -- see below).

    `platform_admin=True` grants the provisioned user the SAME full IT-admin-equivalent
    access as the itadmin layer -- act + approve + see everything, not a view-only role
    (owner decision, 28 Aug 2026: the management heads get IT-level power on purpose). Two
    things follow from models.py's frozen `no_pin_admins` CHECK ("a PIN user on a shared
    shop-floor terminal must never hold admin rights"): a platform admin can never be a
    `local_pin` user, so this flips the user to `auth_type='google'` and sets `login_email`
    to their corporate work_email. They STILL get a one-time PIN and must-change flag (the
    day-one path), because PIN login keys off `pin_hash`, not `auth_type` (routers/auth.py) --
    so a head signs in with the PIN, is forced to change it, and is a full admin immediately,
    while Google sign-in also works once they use it. A head with no work_email on file cannot
    be made an admin this way; that returns "no_email" rather than tripping the CHECK at commit.
    """
    user = db.scalar(
        select(User).join(Employee, User.employee_id == Employee.id).where(
            Employee.employee_code == employee_code
        )
    )
    if user is None:
        return None, "no_user"
    if not user.is_active:
        return None, "inactive"
    if platform_admin:
        employee = db.get(Employee, user.employee_id)
        email = user.login_email or (employee.work_email if employee else None)
        if not email:
            return None, "no_email"
        user.login_email = email
        user.auth_type = "google"  # never local_pin for an admin (models.py no_pin_admins)
        user.is_platform_admin = True
    issued = issue_one_time_pin(db, user, pin=pin, length=length)
    return issued, "provisioned"


# ── functional-mailbox provisioning (shared core) ────────────────────────────────
# MM OS is moving to FUNCTIONAL-MAILBOX accounts (purchase.c2@, central.stores@, sales@)
# rather than personal names. This is the ONE per-row core shared by two callers so their
# behaviour can never drift:
#   * the CLI loader  scripts/provision_functional.py  (roster CSV -> accounts)
#   * the admin API   POST /api/admin/accounts[/bulk]  (routers/people.py)
# It is idempotent, keyed on employee_code, and honours the "blank means leave unset"
# contract for approval_level / platform_admin exactly the way the roster loader documents.


@dataclass
class AccountResult:
    """Outcome of provisioning one functional account. Attribute names are the ones the CLI
    report and PIN-handout writer already consume, so both callers read the same result."""

    employee_code: str
    login_email: str
    employee_action: str  # would_create | created | would_update | updated | unchanged
    user_action: str      # would_create | created | pin_kept | pin_reset | pin_issued
                          # | admin_no_email | would_issue_pin | would_flag_admin_no_email | unchanged
    role: str
    platform_admin: bool  # applied (commit) or requested (dry run)
    approval_level: str | None = None
    pin: str | None = None


def label_from_email(email: str) -> str:
    """A readable full_name from the mailbox local-part, e.g. "purchase.c2@m-mines.com"
    -> "Purchase C2". Falls back to the raw local-part if it has no word characters at all."""
    local = email.split("@", 1)[0]
    words = [w for w in local.replace(".", " ").replace("_", " ").replace("-", " ").split() if w]
    return " ".join(w.capitalize() for w in words) or local


def _ensure_functional_employee(
    db: OrmSession,
    *,
    employee_code: str,
    login_email: str,
    department: str,
    role: str,
    approval_level: str | None,
    commit: bool,
) -> tuple[Employee | None, str]:
    """Idempotent, keyed on employee_code. Never creates a second Employee for a code that
    already exists; updates work_email/hr_department (and the derived label) in place. A blank
    approval_level never overwrites one a human has since set."""
    existing = db.scalar(select(Employee).where(Employee.employee_code == employee_code))
    label = label_from_email(login_email)

    if existing is None:
        if not commit:
            return None, "would_create"
        emp = Employee(
            employee_code=employee_code,
            full_name=label,
            work_email=login_email,
            hr_department=department,
            division=department or "Functional",
            job_title=FUNCTIONAL_JOB_TITLE,
            band="N/A",
            status="active",
            notes=f"functional mailbox; requested role: {role} (no Grant created -- see TODO)",
        )
        if approval_level:
            emp.approval_level = approval_level
        db.add(emp)
        db.flush()  # need emp.id for the User row
        return emp, "created"

    changed = (
        (existing.work_email or None) != (login_email or None)
        or (existing.hr_department or None) != (department or None)
        or existing.full_name != label
        or (approval_level and (existing.approval_level or None) != approval_level)
    )
    if not commit:
        return existing, ("would_update" if changed else "unchanged")

    existing.work_email = login_email
    existing.hr_department = department
    existing.full_name = label
    if approval_level:  # blank never overwrites an approval_level already on file
        existing.approval_level = approval_level
    return existing, ("updated" if changed else "unchanged")


def _ensure_functional_user(
    db: OrmSession,
    employee: Employee | None,
    *,
    login_email: str,
    platform_admin: bool,
    commit: bool,
    reset: bool,
    pin_length: int,
) -> tuple[str, str | None]:
    """Returns (user_action, pin_or_None). Idempotent: re-running never duplicates a User and
    never resets an already-issued PIN unless `reset=True`. Granting platform_admin flips the
    user to google auth (models.py no_pin_admins forbids a local_pin admin) -- same mechanism
    as provision_by_code above."""
    user = None
    if employee is not None:
        user = db.scalar(select(User).where(User.employee_id == employee.id))

    if user is None:
        if not commit:
            return "would_create", None
        user = User(employee_id=employee.id, auth_type="google", login_email=login_email)
        db.add(user)
        db.flush()
        if platform_admin:
            user.is_platform_admin = True  # already google auth with login_email set
        pin = issue_one_time_pin(db, user, length=pin_length)
        return "created", pin

    # existing user
    if not commit:
        if platform_admin and not user.is_platform_admin and not (user.login_email or login_email):
            return "would_flag_admin_no_email", None
        already_issued = user.pin_set_at is not None
        return ("would_issue_pin" if (reset or not already_issued) else "unchanged"), None

    if platform_admin and not user.is_platform_admin:
        email = user.login_email or login_email
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


def provision_account(
    db: OrmSession,
    *,
    employee_code: str,
    login_email: str,
    department: str,
    role: str = DEFAULT_FUNCTIONAL_ROLE,
    approval_level: str | None = None,
    platform_admin: bool = False,
    commit: bool = True,
    reset: bool = False,
    pin_length: int = 6,
) -> AccountResult:
    """Provision ONE functional-mailbox account, idempotently, keyed on employee_code.

    With commit=False nothing is written and the returned actions are the "would_*" preview
    the dry run shows; the caller is responsible for db.rollback()/db.commit() around a batch.
    A one-time must-change PIN is issued for a freshly created user, or reissued when reset=True
    (an already-issued PIN is otherwise left alone). Blank approval_level / falsey platform_admin
    never demote an existing account."""
    employee, employee_action = _ensure_functional_employee(
        db,
        employee_code=employee_code,
        login_email=login_email,
        department=department,
        role=role,
        approval_level=approval_level,
        commit=commit,
    )
    user_action, pin = _ensure_functional_user(
        db,
        employee,
        login_email=login_email,
        platform_admin=platform_admin,
        commit=commit,
        reset=reset,
        pin_length=pin_length,
    )
    platform_admin_applied = bool(
        commit and employee is not None and user_action != "admin_no_email" and platform_admin
    )
    return AccountResult(
        employee_code=employee_code,
        login_email=login_email,
        employee_action=employee_action,
        user_action=user_action,
        role=role,
        platform_admin=platform_admin_applied if commit else platform_admin,
        approval_level=approval_level,
        pin=pin,
    )
