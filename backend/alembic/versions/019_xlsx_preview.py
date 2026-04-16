"""Add spreadsheet_preview JSONB column to email_attachments

Revision ID: 019_xlsx_preview
Revises: 018_audit_log_cascade
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "019_xlsx_preview"
down_revision = "018_audit_log_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_attachments",
        sa.Column("spreadsheet_preview", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_attachments", "spreadsheet_preview")
