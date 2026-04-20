"""Add private notes column to time_entries

Revision ID: 027_time_entry_notes
Revises: 026_forwarded_email
Create Date: 2026-04-20

Adds a nullable ``notes`` column on ``time_entries`` so users can attach
private context (blockers, reminders, context-switch notes) to an entry
without polluting the public ``description`` that shows up in approvals,
exports, and invoices.
"""
from alembic import op
import sqlalchemy as sa

revision = "027_time_entry_notes"
down_revision = "026_forwarded_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "time_entries",
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("time_entries", "notes")
