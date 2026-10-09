"""Record the real session authentication method; legacy admin sessions reauthenticate.

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("auth_method", sa.String(16), nullable=False, server_default="legacy"))


def downgrade():
    op.drop_column("sessions", "auth_method")
