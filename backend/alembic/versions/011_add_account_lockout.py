"""Add account lockout columns to users table.

Revision ID: 011_account_lockout
Revises: 010_tenant_settings
Create Date: 2026-04-04
"""

from alembic import op
import sqlalchemy as sa

revision = "011_account_lockout"
down_revision = "010_tenant_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
