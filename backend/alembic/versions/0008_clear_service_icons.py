"""clear massive base64 icons to fix payload size

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute('UPDATE services SET icon = NULL')

def downgrade() -> None:
    pass
