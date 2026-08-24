"""SQLAlchemy models for the `servicedesk` database. Mirrors docs/07-service-desk.md's
schema exactly (tickets, proposals, decisions, comments, events) with one deliberate change:
every Postgres-only type (`uuid`, `jsonb`) is expressed with a portable SQLAlchemy type
(`sqlalchemy.Uuid`, `sqlalchemy.JSON`) so this module — and every test built on it — runs
unchanged on SQLite here and on Postgres in production. See `## Deviations` in the handoff.

This is Service Desk's own database. It has no foreign key into MM OS: `requester_sub` is
the opaque MM OS subject string, and names/departments are denormalised at write time.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy import JSON, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


TICKET_KINDS = ("support", "automation")
TICKET_PRIORITIES = ("low", "normal", "high", "urgent")
DECISION_KINDS = ("approved", "rejected", "changes_requested")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = _pk()
    ref: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    requester_sub: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    requester_code: Mapped[str] = mapped_column(String(16), nullable=False)
    requester_dept: Mapped[str] = mapped_column(Text, nullable=False)

    service_slug: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    assignee_sub: Mapped[str | None] = mapped_column(Text)
    approver_sub: Mapped[str | None] = mapped_column(Text)  # computed at submit time

    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    proposals: Mapped[list["Proposal"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    comments: Mapped[list["Comment"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    events: Mapped[list["Event"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(f"kind IN {TICKET_KINDS}", name="ck_tickets_kind"),
        CheckConstraint(f"priority IN {TICKET_PRIORITIES}", name="ck_tickets_priority"),
        Index("ix_tickets_status_kind", "status", "kind"),
    )


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[uuid.UUID] = _pk()
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    author_sub: Mapped[str] = mapped_column(Text, nullable=False)
    scope_summary: Mapped[str] = mapped_column(Text, nullable=False)
    effort_days: Mapped[float | None] = mapped_column(Numeric(5, 1))
    resources: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    risks: Mapped[str | None] = mapped_column(Text)
    alternatives: Mapped[str] = mapped_column(Text, nullable=False)  # required — see docs/07
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    created_at: Mapped[datetime] = _now()

    ticket: Mapped["Ticket"] = relationship(back_populates="proposals")

    __table_args__ = (UniqueConstraint("ticket_id", "version", name="uq_proposals_ticket_version"),)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = _pk()
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("proposals.id", ondelete="SET NULL")
    )
    approver_sub: Mapped[str] = mapped_column(Text, nullable=False)
    approver_code: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)  # immutable copy, see app/state_machine.py
    decided_at: Mapped[datetime] = _now()

    ticket: Mapped["Ticket"] = relationship(back_populates="decisions")

    __table_args__ = (CheckConstraint(f"decision IN {DECISION_KINDS}", name="ck_decisions_decision"),)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = _pk()
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    author_sub: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _now()

    ticket: Mapped["Ticket"] = relationship(back_populates="comments")


class Event(Base):
    """Append-only audit trail. Never update or delete a row here — see app/state_machine.py,
    the only module that writes to this table."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = _pk()
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    actor_sub: Mapped[str | None] = mapped_column(Text)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = _now()

    ticket: Mapped["Ticket"] = relationship(back_populates="events")


# ─────────────────────────────────────────────────────────────────────────────
# Administration page (department/roles/SLA/approval-routing config).
#
# All four tables below are Service Desk's own local configuration — none of them duplicate
# MM OS's employee master. `Department` is a plain local lookup (tickets already carry a
# free-text `requester_dept` denormalised from the caller's token; this table makes the list
# of departments Service Desk knows about editable rather than implicitly whatever strings
# have shown up on tickets so far). `LocalRole` denormalises identity (sub/employee_code/
# name/department) at grant time exactly the way `Ticket.requester_*` and `Decision.
# approver_*` already do elsewhere in this file — the fields an admin actually edits are the
# three boolean flags, not the identity snapshot next to them. See handoff/servicedesk-admin.md.
# ─────────────────────────────────────────────────────────────────────────────

SLA_PRIORITIES = TICKET_PRIORITIES  # see handoff: MiniHelp's (low/medium/high/critical) was
# swapped for Service Desk's own ticket-priority vocabulary so an SLA row can actually be
# matched against a real ticket's `priority` column — a critical-but-not-cosmetic deviation
# from "port the model directly", flagged there rather than silently done.

APPROVAL_MODES = ("sequence", "any_of")


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    code: Mapped[str | None] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    sla_configs: Mapped[list["SlaConfig"]] = relationship(back_populates="department", cascade="all, delete-orphan")


class LocalRole(Base):
    """Service-Desk-local grants layered on top of MM OS identity: is this person an IT
    agent (informational mirror only — the `agent` role that actually gates the API comes
    from the MM OS-issued token, see app/mmos_seam.py; this flag does not grant it), a
    department manager, or approver-pool eligible (used to populate the Approval Routing
    tab's approver pickers). Identity fields are a denormalised snapshot taken at grant time,
    the same pattern `Ticket.requester_code`/`Decision.approver_code` already use — not a
    second copy of the employee master to keep in sync, just enough to display."""

    __tablename__ = "local_roles"

    id: Mapped[uuid.UUID] = _pk()
    sub: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    employee_code: Mapped[str] = mapped_column(String(16), nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    is_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_department_manager: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_approver: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SlaConfig(Base):
    """`sla_configs(department_id, priority, response_time_minutes, resolution_time_minutes)`,
    ported from MiniHelp's `server/api/sla.php` — unique on (department, priority), upsert on
    save (see app/routers/admin.py). Priority values are Service Desk's own
    (`low`/`normal`/`high`/`urgent`), not MiniHelp's literal enum — see `SLA_PRIORITIES` above."""

    __tablename__ = "sla_configs"

    id: Mapped[uuid.UUID] = _pk()
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), nullable=False
    )
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    response_time_minutes: Mapped[int] = mapped_column(nullable=False)
    resolution_time_minutes: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    department: Mapped["Department"] = relationship(back_populates="sla_configs")

    __table_args__ = (
        UniqueConstraint("department_id", "priority", name="uq_sla_configs_department_priority"),
        CheckConstraint(f"priority IN {SLA_PRIORITIES}", name="ck_sla_configs_priority"),
    )


class ApprovalRule(Base):
    """The explicit department/category/priority routing matrix — see
    docs `## Approval Routing` in the handoff for the full resolution order (explicit rule,
    most specific first, beats the manager-chain walk in app/org_chart.py, which beats the
    single `ApprovalDefault` fallback below).

    `department` matches `Ticket.requester_dept`, `category` matches `Ticket.service_slug`
    ("request type/category" in the brief — automation requests are the only ones with an
    approver at all, and `kind` is always `"automation"` for those, so the category axis
    that actually varies is which service/system the request concerns), `priority` matches
    `Ticket.priority`. Any of the three may be `NULL`, meaning "matches any" on that axis —
    that is what makes precedence orderable by counting how many axes are pinned down.

    `approvers` is `[{"sub": ..., "employee_code": ...}, ...]`, denormalised at save time
    exactly like `Decision.approver_sub`/`approver_code` — picked from Service Desk's own
    approver pool (`LocalRole.is_approver`), not a second copy of the employee master.
    `mode` records the intended policy (`sequence` vs `any_of`) for display and for a future
    multi-step approval schema; v1's single `Ticket.approver_sub` column means today's
    resolution always names one primary approver — see `## Not done`.
    """

    __tablename__ = "approval_rules"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    department: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(String(16))
    approvers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="any_of")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"priority IS NULL OR priority IN {TICKET_PRIORITIES}", name="ck_approval_rules_priority"),
        CheckConstraint(f"mode IN {APPROVAL_MODES}", name="ck_approval_rules_mode"),
    )


class ApprovalDefault(Base):
    """The guaranteed fallback approver: used only when no explicit `ApprovalRule` matches
    *and* the manager-chain walk (`app/org_chart.compute_approver`) raises `NoApproverFound`
    — today's actual failure mode (62 of 73 managers do not resolve). A single row; the admin
    router always upserts/returns the first (and only) one. Empty at first boot, matching
    "Service Desk starts empty" (README) — the admin must set this explicitly."""

    __tablename__ = "approval_default"

    id: Mapped[uuid.UUID] = _pk()
    sub: Mapped[str] = mapped_column(Text, nullable=False)
    employee_code: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
