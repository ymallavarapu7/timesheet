"""Re-seed ``setting_definitions`` so existing deployments pick up
``tenant_default_timezone``.

Revision ID: 030_seed_tenant_timezone_setting
Revises: 029_tenant_timezone
Create Date: 2026-04-21

No DDL. Just re-runs the idempotent catalog seed (``seed_sync``) so the new
``tenant_default_timezone`` key is inserted on deployments that already ran
migration 028. Existing catalog rows are untouched — the seed uses
``INSERT ... ON CONFLICT DO NOTHING`` (or ``INSERT OR IGNORE`` on SQLite).

Reversible: ``downgrade`` deletes just the new key.
"""
from alembic import op
from sqlalchemy import text

from app.seed_setting_definitions import seed_sync

revision = "030_seed_tenant_timezone_setting"
down_revision = "029_tenant_timezone"
branch_labels = None
depends_on = None

NEW_KEY = "tenant_default_timezone"


def upgrade() -> None:
    connection = op.get_bind()
    seed_sync(connection)


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        text("DELETE FROM setting_definitions WHERE key = :key"),
        {"key": NEW_KEY},
    )
