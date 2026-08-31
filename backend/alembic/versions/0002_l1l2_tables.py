"""L1/L2 phase tables

Additive migration for the in-house backend+integration phase (28 Aug 2026). It adds the
tables the models grew AFTER 0001 that no migration yet creates — which is why the live
deploy 500s (PIN login reads `pin_must_change` and the shared limiter reads `rate_limits`,
neither of which exists on the server).

Runs against a live Postgres that already has every 0001 table + its data, so it ONLY
creates new tables and touches nothing else. Hand-written for the same reason 0001 was:
there is no live Postgres on the build machine to autogenerate against.

Scope note — four tables, not six. `llm_registrations` and `llm_usage_daily` are sometimes
grouped with the "new" L1/L2 tables, but 0001 already creates them (see
0001_initial_schema.py), so they exist on the live DB and are deliberately NOT recreated here
— doing so would raise "relation already exists" and break the deploy. The genuinely
un-migrated tables are exactly: rate_limits, pin_must_change, llm_features,
llm_feature_usage_daily. Mirrors app/models.py (RateLimit), app/provision.py (PinMustChange)
and app/llm_control.py (LlmFeature, LlmFeatureUsageDaily) column-for-column.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-31

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def upgrade() -> None:
    # pgcrypto (for gen_random_uuid) is already installed by 0001; IF NOT EXISTS keeps this
    # safe if 0002 is ever applied first on a fresh DB.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── shared rate-limit counters (multi-worker-safe) ───────────────────
    op.create_table(
        "rate_limits",
        _uuid_pk(),
        sa.Column("bucket", sa.String(length=96), nullable=False),
        sa.Column("window_key", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("bucket", "window_key", name="uq_rate_limit_bucket_window"),
    )
    op.create_index("ix_rate_limits_window", "rate_limits", ["window_key"])

    # ── one-time PIN "must change on first login" flag ───────────────────
    # No surrogate id: user_id IS the primary key (a user is either flagged or not).
    op.create_table(
        "pin_must_change",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    # ── LLM control plane: per-feature governance ────────────────────────
    op.create_table(
        "llm_features",
        _uuid_pk(),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        # models.py default=list (Python-side); a server default of '[]'::jsonb is applied too
        # so a bare INSERT that omits these NOT NULL columns still succeeds — same belt-and-
        # braces approach 0001 takes for audit_log.metadata / revocations.purge_after.
        sa.Column("allowed_providers", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("allowed_models", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("disabled_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["disabled_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("service_id", "feature_key", name="uq_llm_feature_service_key"),
    )

    op.create_table(
        "llm_feature_usage_daily",
        _uuid_pk(),
        sa.Column("feature_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Numeric(20, 0), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Numeric(20, 0), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["feature_id"], ["llm_features.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("feature_id", "day", name="uq_llm_feature_usage_feature_day"),
    )


def downgrade() -> None:
    # Reverse dependency order. Extension left in place (see 0001 downgrade).
    op.drop_table("llm_feature_usage_daily")
    op.drop_table("llm_features")
    op.drop_table("pin_must_change")
    op.drop_index("ix_rate_limits_window", table_name="rate_limits")
    op.drop_table("rate_limits")
