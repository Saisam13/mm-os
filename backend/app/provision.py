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
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session as OrmSession, mapped_column

from .models import Base, Employee, User
from .security import hash_pin


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
