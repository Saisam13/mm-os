"""Actor snapshots and durable transactional activity delivery."""
from alembic import op
import sqlalchemy as sa

revision = "20261007_activity"
down_revision = "20261006_approval"
branch_labels = depends_on = None

SNAPSHOTS = {"tickets": ["requester_name"], "proposals": ["author_name", "author_code"],
             "comments": ["author_name", "author_code"], "decisions": ["approver_name"],
             "events": ["actor_name", "actor_code"]}


def upgrade():
    for table, fields in SNAPSHOTS.items():
        for field in fields:
            op.add_column(table, sa.Column(field, sa.String(32 if field.endswith("_code") else 180)))
    op.create_table("activity_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("activity_delivery",
        sa.Column("event_id", sa.String(36), sa.ForeignKey("activity_events.event_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(64)))
    op.create_index("ix_activity_delivery_pending", "activity_delivery", ["delivered_at", "next_attempt_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION sd_activity_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Activity evidence is immutable'; END $$")
        op.execute("CREATE TRIGGER activity_events_immutable BEFORE UPDATE OR DELETE ON activity_events FOR EACH ROW EXECUTE FUNCTION sd_activity_immutable()")
    else:
        op.execute("CREATE TRIGGER activity_events_no_update BEFORE UPDATE ON activity_events BEGIN SELECT RAISE(ABORT, 'Activity evidence is immutable'); END")
        op.execute("CREATE TRIGGER activity_events_no_delete BEFORE DELETE ON activity_events BEGIN SELECT RAISE(ABORT, 'Activity evidence is immutable'); END")


def downgrade():
    op.drop_table("activity_delivery")
    op.drop_table("activity_events")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION sd_activity_immutable()")
    for table, fields in SNAPSHOTS.items():
        for field in fields:
            op.drop_column(table, field)
