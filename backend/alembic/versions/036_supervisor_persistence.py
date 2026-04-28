"""Persist supervisor through approval

Revision ID: 036_supervisor_persistence
Revises: 035_client_email_domains
Create Date: 2026-04-28

Backs the editable + persisted Supervisor field on the review page.

Today, IngestionTimesheet.extracted_supervisor_name holds the LLM-extracted
name as a free string. The reviewer can see it but cannot:
  (a) override it to a confirmed tenant user, and
  (b) carry it forward to the resulting TimeEntry rows on approval.
After approval, the supervisor signal from the source document is lost.

This migration adds:
  - ingestion_timesheets.supervisor_user_id (FK users.id, nullable):
    the reviewer's confirmed/edited supervisor. Pre-filled by ingestion
    when the extracted name fuzzy-matches an existing tenant user.
  - time_entries.supervisor_user_id (FK users.id, nullable):
    carried forward from IngestionTimesheet on approval.
  - time_entries.supervisor_name_extracted (VARCHAR(255), nullable):
    the original LLM-extracted name, preserved verbatim regardless of
    the reviewer's override. Provides an audit anchor on every approved
    entry so reports can flag mismatches between "who the document said
    approved this" and "who we mapped it to".

Indexes (non-unique) on supervisor_user_id support future "show me all
timesheets I supervised" reports.

extracted_supervisor_name on IngestionTimesheet is preserved as-is.

Backwards compatible: all new columns are nullable. Existing tenants and
approved time entries are untouched.
"""
from alembic import op
import sqlalchemy as sa


revision = "036_supervisor_persistence"
down_revision = "035_client_email_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IngestionTimesheet: reviewer's confirmed supervisor user.
    op.add_column(
        "ingestion_timesheets",
        sa.Column(
            "supervisor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_ingestion_timesheets_supervisor",
        "ingestion_timesheets",
        ["supervisor_user_id"],
    )

    # TimeEntry: supervisor carried forward + the original extracted name.
    op.add_column(
        "time_entries",
        sa.Column(
            "supervisor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "time_entries",
        sa.Column(
            "supervisor_name_extracted",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_time_entries_supervisor",
        "time_entries",
        ["supervisor_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_time_entries_supervisor", table_name="time_entries")
    op.drop_column("time_entries", "supervisor_name_extracted")
    op.drop_column("time_entries", "supervisor_user_id")

    op.drop_index("ix_ingestion_timesheets_supervisor", table_name="ingestion_timesheets")
    op.drop_column("ingestion_timesheets", "supervisor_user_id")
