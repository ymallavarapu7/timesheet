"""Add ON DELETE CASCADE to ingested_emails.mailbox_id FK

Revision ID: 016_mailbox_cascade_delete
Revises: 015_add_platform_settings
Create Date: 2026-04-08
"""
from alembic import op

revision = "016_mailbox_cascade_delete"
down_revision = "015_add_platform_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ingested_emails_mailbox_id_fkey", "ingested_emails", type_="foreignkey")
    op.create_foreign_key(
        "ingested_emails_mailbox_id_fkey",
        "ingested_emails", "mailboxes",
        ["mailbox_id"], ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("ingested_emails_mailbox_id_fkey", "ingested_emails", type_="foreignkey")
    op.create_foreign_key(
        "ingested_emails_mailbox_id_fkey",
        "ingested_emails", "mailboxes",
        ["mailbox_id"], ["id"],
    )
