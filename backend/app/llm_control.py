"""LLM control plane -- per-service, per-feature governance (INT-5).

MM OS is the ONE place every AI feature across every service is governed from. The frozen
`LlmRegistration` / `LlmUsageDaily` tables (app/models.py) hold a single service-level row
each -- enough for "is this service's LLM on, and how much did it use in total," but not for
the real ask: a service (Sales Hub, item-code-studio) has SEVERAL named AI features, each
potentially on a different provider/model, each individually governable and metered.

This module adds that layer WITHOUT touching the frozen models.py -- the only permitted
models.py edit this phase is the shared rate-limiter table. These two tables attach to the
same `Base.metadata`, so the test harness (conftest's create_all) and Alembic (via
alembic/env.py, which imports this module) both see them.

THE BOUNDARY -- written down on purpose (docs/15-llm-control-plane.md): MM OS governs
policy, enablement and usage. It NEVER holds a provider API key. Keys live in the service
that calls the provider. The service reports which provider/model it used and how much;
MM OS decides whether that feature is allowed and which providers/models it may use, and can
flip a kill switch. Secrets never enter this control plane -- the service-facing endpoints in
routers/agent.py strip any key-shaped field before it can be stored, the same way the
heartbeat already does.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text,
    UniqueConstraint, func, select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session as OrmSession, mapped_column, relationship

from .models import Base, LlmRegistration, Service


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class LlmFeature(Base):
    """One named AI feature belonging to one service -- e.g. Sales Hub's "lead_enrichment"
    or item-code-studio's "code_match". Carries the provider/model the service DECLARED it
    uses, plus the policy MM OS imposes on it (which providers/models it MAY use, and a
    per-feature kill switch that is ANDed with the service-level one)."""

    __tablename__ = "llm_features"

    id: Mapped[uuid.UUID] = _pk()
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(Text)

    # What the service reported it is using (declared, observed) -- not policy.
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))

    # Policy MM OS imposes. Empty list = "no restriction" (any provider/model the service
    # declares is accepted); a non-empty list is an allowlist the service must stay within.
    allowed_providers: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    allowed_models: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    # Per-feature kill switch. Effective enablement is (service.enabled AND feature.enabled).
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    disabled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_reason: Mapped[str | None] = mapped_column(Text)

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    service: Mapped[Service] = relationship()

    __table_args__ = (
        UniqueConstraint("service_id", "feature_key", name="uq_llm_feature_service_key"),
    )


class LlmFeatureUsageDaily(Base):
    """Per-feature daily usage counters. Accumulated, never overwritten, one row per
    (feature, day) -- the same shape as the frozen service-level LlmUsageDaily."""

    __tablename__ = "llm_feature_usage_daily"

    id: Mapped[uuid.UUID] = _pk()
    feature_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_features.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Numeric(20, 0), default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Numeric(20, 0), default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("feature_id", "day", name="uq_llm_feature_usage_feature_day"),
    )


# ── helpers shared by the admin and service-facing routers ─────────────────────
def get_or_create_feature(
    db: OrmSession,
    service: Service,
    feature_key: str,
    *,
    name: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[LlmFeature, bool]:
    """Return (feature, created). A service declaring or reporting a feature that MM OS has
    never seen auto-registers it, visible and enabled, rather than being silently dropped --
    the same "never silently blank" principle the service-level registration follows."""
    feature = db.scalar(
        select(LlmFeature).where(
            LlmFeature.service_id == service.id, LlmFeature.feature_key == feature_key
        )
    )
    created = False
    if feature is None:
        feature = LlmFeature(
            service_id=service.id, feature_key=feature_key, name=name or feature_key
        )
        db.add(feature)
        created = True
    if name and (created or not feature.name):
        feature.name = name
    if provider:
        feature.provider = provider
    if model:
        feature.model = model
    feature.last_seen_at = datetime.now(timezone.utc)
    db.flush()
    return feature, created


def service_registration(db: OrmSession, service: Service) -> LlmRegistration | None:
    return db.scalar(select(LlmRegistration).where(LlmRegistration.service_id == service.id))


def service_llm_enabled(db: OrmSession, service: Service) -> bool:
    """Service-level kill switch. A service with no registration row yet is open by default
    (matches routers/agent.py's `_get_or_create_registration` default of enabled=True)."""
    reg = service_registration(db, service)
    return True if reg is None else bool(reg.enabled)


def feature_policy_dict(feature: LlmFeature, *, service_enabled: bool) -> dict:
    """The per-feature view a service consumes to decide what it may do. `enabled` is the
    effective value (service AND feature); the service never has to combine them itself."""
    return {
        "feature_key": feature.feature_key,
        "name": feature.name,
        "enabled": bool(service_enabled and feature.enabled),
        "feature_enabled": bool(feature.enabled),
        "provider": feature.provider,
        "model": feature.model,
        "allowed_providers": list(feature.allowed_providers or []),
        "allowed_models": list(feature.allowed_models or []),
    }


def record_feature_usage(
    db: OrmSession,
    feature: LlmFeature,
    *,
    requests: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    day: date | None = None,
) -> LlmFeatureUsageDaily:
    """Accumulate one usage report into the (feature, day) row, creating it if needed."""
    day = day or date.today()
    row = db.scalar(
        select(LlmFeatureUsageDaily).where(
            LlmFeatureUsageDaily.feature_id == feature.id, LlmFeatureUsageDaily.day == day
        )
    )
    if row is None:
        row = LlmFeatureUsageDaily(feature_id=feature.id, day=day)
        db.add(row)
        db.flush()
    row.requests += int(requests or 0)
    row.input_tokens += int(input_tokens or 0)
    row.output_tokens += int(output_tokens or 0)
    return row
