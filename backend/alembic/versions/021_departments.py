"""Add managed departments table; backfill from distinct user.department per tenant

Revision ID: 021_departments
Revises: 020_attach_html
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "021_departments"
down_revision = "020_attach_html"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_departments_tenant_name"),
    )
    op.create_index("ix_departments_tenant_id", "departments", ["tenant_id"])

    # Backfill: insert one row per (tenant_id, distinct trimmed department).
    op.execute(
        """
        INSERT INTO departments (tenant_id, name, created_at, updated_at)
        SELECT DISTINCT tenant_id, btrim(department), NOW(), NOW()
        FROM users
        WHERE department IS NOT NULL
          AND btrim(department) <> ''
          AND tenant_id IS NOT NULL
        ON CONFLICT (tenant_id, name) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_departments_tenant_id", table_name="departments")
    op.drop_table("departments")
