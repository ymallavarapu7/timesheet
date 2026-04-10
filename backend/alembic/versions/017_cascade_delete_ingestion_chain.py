"""Add ON DELETE CASCADE to ingestion chain FKs

Fixes delete chain: mailboxes → ingested_emails → email_attachments → ingestion_timesheets

Revision ID: 017_cascade_delete_ingestion_chain
Revises: 016_mailbox_cascade_delete
Create Date: 2026-04-08
"""
from alembic import op

revision = "017_ingestion_cascade"
down_revision = "016_mailbox_cascade_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # email_attachments.email_id → ingested_emails
    op.drop_constraint("email_attachments_email_id_fkey", "email_attachments", type_="foreignkey")
    op.create_foreign_key(
        "email_attachments_email_id_fkey",
        "email_attachments", "ingested_emails",
        ["email_id"], ["id"],
        ondelete="CASCADE",
    )

    # ingestion_timesheets.email_id → ingested_emails
    op.drop_constraint("ingestion_timesheets_email_id_fkey", "ingestion_timesheets", type_="foreignkey")
    op.create_foreign_key(
        "ingestion_timesheets_email_id_fkey",
        "ingestion_timesheets", "ingested_emails",
        ["email_id"], ["id"],
        ondelete="CASCADE",
    )

    # ingestion_timesheets.attachment_id → email_attachments
    op.drop_constraint("ingestion_timesheets_attachment_id_fkey", "ingestion_timesheets", type_="foreignkey")
    op.create_foreign_key(
        "ingestion_timesheets_attachment_id_fkey",
        "ingestion_timesheets", "email_attachments",
        ["attachment_id"], ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("ingestion_timesheets_attachment_id_fkey", "ingestion_timesheets", type_="foreignkey")
    op.create_foreign_key(
        "ingestion_timesheets_attachment_id_fkey",
        "ingestion_timesheets", "email_attachments",
        ["attachment_id"], ["id"],
    )

    op.drop_constraint("ingestion_timesheets_email_id_fkey", "ingestion_timesheets", type_="foreignkey")
    op.create_foreign_key(
        "ingestion_timesheets_email_id_fkey",
        "ingestion_timesheets", "ingested_emails",
        ["email_id"], ["id"],
    )

    op.drop_constraint("email_attachments_email_id_fkey", "email_attachments", type_="foreignkey")
    op.create_foreign_key(
        "email_attachments_email_id_fkey",
        "email_attachments", "ingested_emails",
        ["email_id"], ["id"],
    )
