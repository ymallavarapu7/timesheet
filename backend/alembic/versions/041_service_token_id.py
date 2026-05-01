"""Add public token_id column to service_tokens for indexed lookup.

Revision ID: 041_service_token_id
Revises: 040_user_roles_array
Create Date: 2026-05-01

Background:
    Inbound service-token authentication used to load every active
    token for the tenant and bcrypt-compare against each one in a
    Python loop. With many tokens that's O(n) bcrypt operations per
    request — slow and wasteful.

    New shape: tokens are minted as ``<token_id>.<secret>`` where the
    token_id is a short opaque public value persisted alongside the
    bcrypt'd secret. Lookup becomes one indexed query keyed by
    token_id, then exactly one bcrypt comparison.

This migration:
    - Adds ``service_tokens.token_id`` (VARCHAR(32), nullable, unique).
    - Creates an index on ``token_id`` for the indexed lookup path.

Existing tokens have NULL ``token_id`` and continue to work via the
legacy loop fallback in ``get_service_token_tenant``. Operators can
rotate to the new format on their own schedule.
"""
from alembic import op
import sqlalchemy as sa


revision = "041_service_token_id"
down_revision = "040_user_roles_array"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_tokens",
        sa.Column("token_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_service_tokens_token_id",
        "service_tokens",
        ["token_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_service_tokens_token_id", table_name="service_tokens")
    op.drop_column("service_tokens", "token_id")
