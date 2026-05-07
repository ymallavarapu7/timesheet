"""mailbox needs_reauth flag

Revision ID: 045
Revises: 044
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = "045_mailbox_needs_reauth"
down_revision = "044_user_phones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mailboxes",
        sa.Column(
            "needs_reauth",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("mailboxes", "needs_reauth")
