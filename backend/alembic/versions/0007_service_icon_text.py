"""update service icon to text to support base64 uploads

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.alter_column('services', 'icon', type_=sa.Text(), existing_type=sa.String(length=48))

def downgrade() -> None:
    op.alter_column('services', 'icon', type_=sa.String(length=48), existing_type=sa.Text())
