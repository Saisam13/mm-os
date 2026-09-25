"""First sign-in: personal Gmail addresses, the confirm-your-code-and-set-a-PIN step, and the
lowest role everyone gets by default.

Owner decisions, 25 Sep 2026 (docs/16-decisions.md D-2026-09-25-2):

* One MM OS account per person, pre-created from the people sheet. Shared functional
  mailboxes stay as their own accounts.
* The official (company) email signs in with Google directly. Everyone then confirms their
  employee code and sets a PIN once, so PIN sign-in works too.
* A personal Gmail signs in only if the sheet lists it for that person AND the person types
  the matching employee code the first time. After that it signs in directly. Listing an
  address is not enough on its own: the sheet came from a self-filled form.
* A company address that is not in the sheet gets an account in department "Unassigned"
  holding each service's lowest role. Any other unknown address is always refused.

The personal address lives in a side table rather than a column on the frozen `users` table,
the same pattern as `pin_must_change` in app/provision.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session as OrmSession, mapped_column

from .models import Base, Grant, Service, ServiceRole, User


class PersonalEmail(Base):
    """A second Google address a user may sign in with. `verified_at` stays empty until the
    person has proved it by typing their employee code once; until then it only unlocks the
    confirm-your-code step, never a session."""

    __tablename__ = "personal_emails"

    email: Mapped[str] = mapped_column(Text, primary_key=True)  # stored lowercased
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def personal_email_for(db: OrmSession, user: User) -> PersonalEmail | None:
    return db.scalar(select(PersonalEmail).where(PersonalEmail.user_id == user.id))


def needs_onboarding(user: User) -> bool:
    """True until the person has confirmed their employee code and set a PIN."""
    return user.pin_set_at is None


def lowest_roles(db: OrmSession) -> dict[str, ServiceRole]:
    """slug -> the role an unconfigured person gets: the role marked default (Admin → Roles
    "Make default"). A service with no default role gives unconfigured people nothing."""
    rows = db.execute(
        select(Service, ServiceRole)
        .join(ServiceRole, ServiceRole.service_id == Service.id)
        .where(Service.is_active.is_(True), ServiceRole.is_default.is_(True))
    ).all()
    return {s.slug: r for s, r in rows}


def grant_lowest_roles(db: OrmSession, user: User, *, reason: str = "lowest role (unconfigured)") -> list[str]:
    """Give `user` every service's lowest role they do not already hold a grant for."""
    held = {g.service_id for g in db.scalars(select(Grant).where(Grant.user_id == user.id))}
    given = []
    for slug, role in lowest_roles(db).items():
        if role.service_id in held:
            continue
        db.add(Grant(user_id=user.id, service_id=role.service_id, service_role_id=role.id, reason=reason))
        given.append(slug)
    db.flush()
    return given
