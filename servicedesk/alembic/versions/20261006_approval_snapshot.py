"""Snapshot approval policy and record completed sequence steps.

Revision ID: 20261006_approval
Revises: fa74c3024f58
"""
from alembic import op
import sqlalchemy as sa

revision = "20261006_approval"
down_revision = "fa74c3024f58"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tickets", sa.Column("approval_policy", sa.JSON(), nullable=True))
    op.add_column("tickets", sa.Column("approved_by", sa.JSON(), nullable=True))
    # Existing in-flight tickets retain their historically designated single approver.
    # New tickets snapshot the full rule. Operators must review old multi-step requests.


def downgrade():
    op.drop_column("tickets", "approved_by")
    op.drop_column("tickets", "approval_policy")
