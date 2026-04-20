"""Add forwarded_from_email/name on ingested_emails

Revision ID: 026_forwarded_email
Revises: 025_client_contacts
Create Date: 2026-04-20

Captures the original sender of a forwarded email so the review UI can show
who originally submitted the timesheet instead of the forwarder's address.
"""
from alembic import op
import sqlalchemy as sa

revision = "026_forwarded_email"
down_revision = "025_client_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingested_emails",
        sa.Column("forwarded_from_email", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "ingested_emails",
        sa.Column("forwarded_from_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingested_emails", "forwarded_from_name")
    op.drop_column("ingested_emails", "forwarded_from_email")
