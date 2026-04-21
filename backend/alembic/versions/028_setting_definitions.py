"""Add setting_definitions catalog and seed it

Revision ID: 028_setting_definitions
Revises: 027_time_entry_notes
Create Date: 2026-04-21

Introduces the global ``setting_definitions`` catalog — one row per tenant
setting key — and seeds it with every key that the codebase currently reads
from ``TenantSettings``. The per-tenant ``TenantSettings`` table is untouched:
existing rows continue to work, and the accessor layer (``app.core.tenant_settings``)
falls back to ``setting_definitions.default_value`` for any key without a
stored row.

Reversible. ``downgrade`` drops the table; no ``ALTER TYPE`` needed because
``activity_log.activity_type`` is a plain VARCHAR, not a Postgres enum — new
string values like ``TENANT_SETTING_CHANGED`` don't require a schema change.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.seed_setting_definitions import seed_sync

revision = "028_setting_definitions"
down_revision = "027_time_entry_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setting_definitions",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("data_type", sa.String(length=20), nullable=False),
        sa.Column("default_value", JSONB(), nullable=False),
        sa.Column(
            "validation", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "added_in",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'1.0.0'"),
        ),
    )

    # Seed the catalog immediately so a fresh deploy has settings available
    # without a separate management command.
    connection = op.get_bind()
    seed_sync(connection)


def downgrade() -> None:
    op.drop_table("setting_definitions")
