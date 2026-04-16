"""Add rendered_html to email_attachments for source file HTML preview

Revision ID: 020_attach_html
Revises: 019_xlsx_preview
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "020_attach_html"
down_revision = "019_xlsx_preview"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_attachments",
        sa.Column("rendered_html", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_attachments", "rendered_html")
