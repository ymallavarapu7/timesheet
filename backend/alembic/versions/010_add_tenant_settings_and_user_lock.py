"""Add tenant_settings table and user timesheet lock columns.

Revision ID: 010_add_tenant_settings_and_user_lock
Revises: 009_add_line_item_rejection
Create Date: 2026-04-03
"""

from alembic import op
import sqlalchemy as sa

revision = "010_tenant_settings"
down_revision = "009_add_line_item_rejection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_settings_tenant_key"),
    )
    op.create_index("ix_tenant_settings_tenant_id", "tenant_settings", ["tenant_id"])

    op.add_column("users", sa.Column("timesheet_locked", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("timesheet_locked_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "timesheet_locked_reason")
    op.drop_column("users", "timesheet_locked")
    op.drop_index("ix_tenant_settings_tenant_id", table_name="tenant_settings")
    op.drop_table("tenant_settings")
