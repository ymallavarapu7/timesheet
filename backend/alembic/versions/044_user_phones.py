"""Add phones JSONB column to users table.

Revision ID: 044_user_phones
Revises: 043_user_email_aliases
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "044_user_phones"
down_revision = "043_user_email_aliases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "phones",
            JSONB,
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "phones")
