"""SQLAlchemy models. Mirrors docs/02-data-model.md exactly.

MM OS stores four things: who works here, what services exist, who may open which service
in what role, and what happened. Nothing about batteries lives in this database.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ── people ────────────────────────────────────────────────────────────────
class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = _pk()
    employee_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    work_email: Mapped[str | None] = mapped_column(Text, unique=True)
    hr_department: Mapped[str] = mapped_column(Text, nullable=False)
    division: Mapped[str] = mapped_column(Text, nullable=False)
    job_title: Mapped[str] = mapped_column(Text, nullable=False)
    band: Mapped[str] = mapped_column(String(8), nullable=False)
    approval_level: Mapped[str | None] = mapped_column(Text)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL")
    )
    is_approver: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="employee", uselist=False)
    manager: Mapped["Employee"] = relationship(remote_side=[id])

    __table_args__ = (
        CheckConstraint("status IN ('active','suspended','exited')", name="employee_status"),
        Index("ix_employees_dept", "hr_department"),
        Index("ix_employees_manager_id", "manager_id"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    login_email: Mapped[str | None] = mapped_column(Text, unique=True)
    auth_type: Mapped[str] = mapped_column(String(16), default="google", nullable=False)
    pin_hash: Mapped[str | None] = mapped_column(Text)
    pin_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_pin_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()

    employee: Mapped[Employee] = relationship(back_populates="user")
    grants: Mapped[list["Grant"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="Grant.user_id"
    )

    __table_args__ = (
        CheckConstraint("auth_type IN ('google','local_pin')", name="user_auth_type"),
        CheckConstraint("auth_type <> 'local_pin' OR pin_hash IS NOT NULL", name="pin_required"),
        CheckConstraint("auth_type <> 'google' OR login_email IS NOT NULL", name="email_required"),
        # A PIN user on a shared shop-floor terminal must never hold admin rights.
        CheckConstraint(
            "NOT (auth_type = 'local_pin' AND is_platform_admin)", name="no_pin_admins"
        ),
    )

    @property
    def subject(self) -> str:
        return f"user:{self.id}"


# ── service registry ──────────────────────────────────────────────────────
class Service(Base):
    __tablename__ = "services"

    id: Mapped[uuid.UUID] = _pk()
    slug: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    tagline: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(24), default="internal", nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str | None] = mapped_column(String(48))
    launch_mode: Mapped[str] = mapped_column(String(16), default="handoff", nullable=False)
    has_public_surface: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    public_url: Mapped[str | None] = mapped_column(Text)
    health_url: Mapped[str | None] = mapped_column(Text)
    owner_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL")
    )
    service_key_hash: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_at: Mapped[datetime] = _now()

    roles: Mapped[list["ServiceRole"]] = relationship(
        back_populates="service", cascade="all, delete-orphan"
    )
    llm: Mapped["LlmRegistration"] = relationship(
        back_populates="service", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("launch_mode IN ('handoff','embed','external')", name="launch_mode_valid"),
    )


class ServiceRole(Base):
    __tablename__ = "service_roles"

    id: Mapped[uuid.UUID] = _pk()
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    service: Mapped[Service] = relationship(back_populates="roles")

    __table_args__ = (UniqueConstraint("service_id", "key", name="uq_service_role"),)


class Grant(Base):
    """One row = one person may open one service in one role. The whole permission model."""

    __tablename__ = "grants"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    service_role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_roles.id", ondelete="RESTRICT"), nullable=False
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()

    user: Mapped[User] = relationship(back_populates="grants", foreign_keys=[user_id])
    service: Mapped[Service] = relationship()
    role: Mapped[ServiceRole] = relationship()

    __table_args__ = (
        UniqueConstraint("user_id", "service_id", name="uq_grant_user_service"),
        Index("ix_grants_service", "service_id"),
    )


# ── sessions and revocation ───────────────────────────────────────────────
class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()

    __table_args__ = (
        # Partial: only live (unrevoked) sessions are ever looked up by user.
        Index("ix_sessions_user_live", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )


class Revocation(Base):
    """The deny-list services poll. Rows expire once no live token could still carry them."""

    __tablename__ = "revocations"

    id: Mapped[uuid.UUID] = _pk()
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE")
    )
    jti: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime] = _now()
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_revocations_at", "revoked_at"),)


# ── LLM control plane (never holds a key) ─────────────────────────────────
class LlmRegistration(Base):
    __tablename__ = "llm_registrations"

    id: Mapped[uuid.UUID] = _pk()
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    key_present: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    disabled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_reason: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    service: Mapped[Service] = relationship(back_populates="llm")


class LlmUsageDaily(Base):
    __tablename__ = "llm_usage_daily"

    id: Mapped[uuid.UUID] = _pk()
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Numeric(20, 0), default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Numeric(20, 0), default=0, nullable=False)

    __table_args__ = (UniqueConstraint("service_id", "day", name="uq_usage_service_day"),)


# ── shared rate-limit counters (multi-worker-safe) ────────────────────────
class RateLimit(Base):
    """Fixed-window counters shared across every worker/replica through the one Postgres.

    Added for the L1/L2 phase (28 Aug 2026): the PIN-login and service-token limiters were
    in-process deques (routers/auth.py, routers/tokens.py), so with more than one uvicorn
    worker each process kept its own budget and every limit silently became N times more
    permissive -- which is why the deployment was pinned to `--workers 1`. Moving the counter
    into a table shared by all workers makes horizontal scaling safe: one budget, one DB.

    One row per (bucket, window_key). `bucket` is the throttled identity, namespaced by limiter
    -- e.g. "pin:<ip>" or "token:<user_id>". `window_key` is the fixed 60-second window index
    (epoch_seconds // window_seconds), so a whole window's hits share a single row that is
    incremented in place -- the "don't write-amplify under attack" property the in-memory
    version had: an over-budget caller never writes anything at all (see app/ratelimit.py).

    The window is coarse-grained on purpose (a plain integer bucket, not a per-hit timestamp
    row) so the table can never grow faster than one row per active identity per minute, and
    old windows are purged by app/routers/agent.py's existing hourly purge loop.
    """

    __tablename__ = "rate_limits"

    id: Mapped[uuid.UUID] = _pk()
    bucket: Mapped[str] = mapped_column(String(96), nullable=False)
    window_key: Mapped[int] = mapped_column(BigInteger, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        UniqueConstraint("bucket", "window_key", name="uq_rate_limit_bucket_window"),
        Index("ix_rate_limits_window", "window_key"),
    )


# ── audit ─────────────────────────────────────────────────────────────────
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _pk()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(Text)
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", ondelete="SET NULL")
    )
    ip: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        # DESC: the audit log is only ever read newest-first.
        Index("ix_audit_created", text("created_at DESC")),
        Index("ix_audit_actor_created", "actor_user_id", text("created_at DESC")),
    )
