"""Add ``timezone`` column to ``tenants``

Revision ID: 029_tenant_timezone
Revises: 028_setting_definitions
Create Date: 2026-04-21

Adds a nullable ``timezone`` column (IANA name, e.g. ``America/New_York``) to
the ``tenants`` table. NULL means "fall back to UTC" — existing tenants keep
their current behavior.

Reversible: ``downgrade`` drops the column.
"""
from alembic import op
import sqlalchemy as sa

revision = "029_tenant_timezone"
down_revision = "028_setting_definitions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("timezone", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "timezone")
