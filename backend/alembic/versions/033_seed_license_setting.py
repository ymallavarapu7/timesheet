"""Re-seed setting definitions for the ``license_key`` catalog entry.

Revision ID: 033_seed_license_setting
Revises: 032_licensing
Create Date: 2026-04-21
"""
from alembic import op
from sqlalchemy import text

from app.seed_setting_definitions import seed_sync


revision = "033_seed_license_setting"
down_revision = "032_licensing"
branch_labels = None
depends_on = None

NEW_KEY = "license_key"


def upgrade() -> None:
    seed_sync(op.get_bind())


def downgrade() -> None:
    op.get_bind().execute(
        text("DELETE FROM setting_definitions WHERE key = :key"),
        {"key": NEW_KEY},
    )
