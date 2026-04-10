"""Add multi-tenancy: tenants table, tenant_id columns, PLATFORM_ADMIN role.

IMPORTANT — Before running on production:
    1. Back up the database:
           pg_dump -Fc -U timesheet_user -d timesheet_db > \\
               backups/pre_multitenancy_$(date +%Y%%m%%d_%%H%%M%%S).dump
    2. Then apply:
           cd backend && alembic upgrade head

Revision ID: 002_add_multi_tenancy
Revises: 001_baseline_schema
Create Date: 2026-03-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_add_multi_tenancy"
down_revision: Union[str, None] = "001_baseline_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── STEP 1: Create tenants table ──────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", "suspended", name="tenantstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    # ── STEP 2: Insert the default tenant ─────────────────────────────────────
    # All existing rows will be assigned to this tenant (id = 1).
    op.execute("""
        INSERT INTO tenants (name, slug, status, created_at, updated_at)
        VALUES ('Default Tenant', 'default', 'active', NOW(), NOW())
    """)

    # ── STEP 3: Add tenant_id columns with server_default so existing rows ────
    #            get tenant_id = 1 automatically.
    op.add_column(
        "users",
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=True,
            server_default="1",
        ),
    )

    for table in ["clients", "projects", "tasks", "time_entries", "time_off_requests"]:
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id"),
                nullable=False,
                server_default="1",
            ),
        )

    # ── STEP 4: Ensure every existing row explicitly has tenant_id = 1 ────────
    for table in ["users", "clients", "projects", "tasks", "time_entries", "time_off_requests"]:
        op.execute(f"UPDATE {table} SET tenant_id = 1 WHERE tenant_id IS NULL")

    # ── STEP 5: Add indexes on tenant_id ──────────────────────────────────────
    for table in ["users", "clients", "projects", "tasks", "time_entries", "time_off_requests"]:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    # ── STEP 6: Add PLATFORM_ADMIN enum value ─────────────────────────────────
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'PLATFORM_ADMIN'")

    # ── STEP 7: Remove server defaults — new rows must supply tenant_id ───────
    # users stays nullable (for future PLATFORM_ADMIN users who have no tenant).
    for table in ["clients", "projects", "tasks", "time_entries", "time_off_requests"]:
        op.alter_column(table, "tenant_id", existing_type=sa.Integer(), server_default=None)


def downgrade() -> None:
    for table in ["users", "clients", "projects", "tasks", "time_entries", "time_off_requests"]:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")

    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
    op.execute("DROP TYPE IF EXISTS tenantstatus")
    # Note: PostgreSQL enum values cannot be removed; PLATFORM_ADMIN remains in
    # userrole after downgrade but is harmless when unused.
