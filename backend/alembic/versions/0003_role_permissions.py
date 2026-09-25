"""Role permissions and role files

Adds what a role is allowed to do. `services.permission_catalog` holds the service's
declared permissions ({"key": "meaning"}); `service_roles.permissions` lists which of those
keys a role carries, and `service_roles.sort_order` orders roles lowest to highest access.
All three arrive through the role-file import (app/roles_io.py) or the admin API.

Additive only: three nullable-free columns with server defaults, so every existing row is
valid the moment the migration lands and nothing else is touched.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-25

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "services",
        sa.Column("permission_catalog", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "service_roles",
        sa.Column("permissions", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "service_roles",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
    )


def downgrade() -> None:
    op.drop_column("service_roles", "sort_order")
    op.drop_column("service_roles", "permissions")
    op.drop_column("services", "permission_catalog")
