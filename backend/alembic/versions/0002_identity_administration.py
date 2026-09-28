"""identity administration: departments, delegation, agents and multi-role grants

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                     server_default=sa.text("gen_random_uuid()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "departments", _id(),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    # Preserve every existing department spelling as a controlled record, then link people.
    op.execute("""
        INSERT INTO departments (key, name)
        SELECT lower(regexp_replace(trim(hr_department), '[^a-zA-Z0-9]+', '-', 'g'))
               || '-' || substr(md5(trim(hr_department)), 1, 8), trim(hr_department)
        FROM employees GROUP BY trim(hr_department)
        ON CONFLICT (name) DO NOTHING
    """)
    op.add_column("employees", sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("employees", sa.Column("onboarding_ref", sa.String(128), nullable=True))
    op.create_foreign_key("fk_employee_department", "employees", "departments", ["department_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_employee_onboarding_ref", "employees", ["onboarding_ref"])
    op.execute("""
        UPDATE employees e SET department_id = d.id
        FROM departments d WHERE d.name = trim(e.hr_department)
    """)

    op.create_table(
        "user_capabilities", _id(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("scope_department_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scope_department_id"], ["departments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("user_id", "capability", "scope_department_id", name="uq_user_capability_scope"),
    )
    op.create_table(
        "agent_identities", _id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("kind", sa.String(24), nullable=False, server_default="agent"),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("credential_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="SET NULL"),
        sa.CheckConstraint("kind IN ('agent','automation','integration')", name="agent_kind"),
    )
    op.add_column("grants", sa.Column("origin", sa.String(24), nullable=False, server_default="manual"))
    op.drop_constraint("uq_grant_user_service", "grants", type_="unique")
    op.create_unique_constraint("uq_grant_user_service_role", "grants", ["user_id", "service_id", "service_role_id"])


def downgrade() -> None:
    op.drop_constraint("uq_grant_user_service_role", "grants", type_="unique")
    # Downgrade cannot represent multiple roles. Keep one deterministic role per service.
    op.execute("""
        DELETE FROM grants WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY user_id, service_id ORDER BY created_at, id
                ) AS rn FROM grants
            ) ranked WHERE rn > 1
        )
    """)
    op.create_unique_constraint("uq_grant_user_service", "grants", ["user_id", "service_id"])
    op.drop_column("grants", "origin")
    op.drop_table("agent_identities")
    op.drop_table("user_capabilities")
    op.drop_constraint("uq_employee_onboarding_ref", "employees", type_="unique")
    op.drop_constraint("fk_employee_department", "employees", type_="foreignkey")
    op.drop_column("employees", "onboarding_ref")
    op.drop_column("employees", "department_id")
    op.drop_table("departments")
