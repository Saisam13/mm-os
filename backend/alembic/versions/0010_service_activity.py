"""Durable cross-service business activity with immutable PostgreSQL payloads."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0010"
down_revision = "0009"
branch_labels = depends_on = None


def upgrade():
    op.create_table("service_activity",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("source_service_id", UUID(as_uuid=True), nullable=False),
        sa.Column("service_slug", sa.String(64), nullable=False),
        sa.Column("actor_subject", sa.String(180), nullable=False),
        sa.Column("actor_name", sa.String(180)), sa.Column("actor_code", sa.String(32)),
        sa.Column("department_id", UUID(as_uuid=True)),
        sa.Column("action", sa.String(96), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False), sa.Column("target_id", sa.String(180), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False), sa.Column("restricted", sa.Boolean(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("payload", JSONB(), nullable=False), sa.Column("digest", sa.String(64), nullable=False),
        sa.UniqueConstraint("source_service_id", "event_id", name="uq_service_activity_event"))
    op.create_index("ix_service_activity_time", "service_activity", ["occurred_at", "id"])
    op.create_index("ix_service_activity_actor", "service_activity", ["actor_subject", "occurred_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION mmos_activity_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Activity evidence is immutable'; END $$")
        op.execute("CREATE TRIGGER service_activity_immutable BEFORE UPDATE OR DELETE ON service_activity FOR EACH ROW EXECUTE FUNCTION mmos_activity_immutable()")


def downgrade():
    op.drop_table("service_activity")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION mmos_activity_immutable()")
