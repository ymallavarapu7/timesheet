"""Simplify supervisor: drop FK columns, keep one editable string

Revision ID: 037_supervisor_simplify
Revises: 036_supervisor_persistence
Create Date: 2026-04-28

Migration 036 introduced supervisor_user_id (FK to users.id) on both
ingestion_timesheets and time_entries, plus a supervisor_name_extracted
column on time_entries. The model assumed every supervisor would be a
tenant user that could be picked from a dropdown.

That assumption was wrong. In the staffing-firm model the supervisor on
a timesheet is typically a person at the *client* (e.g., Jianli Xiao at
DXC), not an Acuent employee. Auto-creating User rows for them would
clutter the user list with non-employees and trigger downstream
permission/notification logic that doesn't apply.

The simpler model we're settling on:

  - ingestion_timesheets.extracted_supervisor_name is the editable string
    the reviewer confirms or edits. Pre-filled by ingestion from the
    LLM's supervisor_name extraction. The original LLM value stays
    preserved in extracted_data JSON for audit.
  - time_entries.supervisor_name is a renamed copy of the previous
    supervisor_name_extracted column. It carries the reviewer-confirmed
    value forward at approval time.

This migration:
  - Drops supervisor_user_id (and its index) from both tables.
  - Renames time_entries.supervisor_name_extracted to supervisor_name.

Backwards compat: 036 was applied locally but never to production. The
columns being dropped here have no production data depending on them.
"""
from alembic import op


revision = "037_supervisor_simplify"
down_revision = "036_supervisor_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_time_entries_supervisor", table_name="time_entries")
    op.drop_constraint(
        "time_entries_supervisor_user_id_fkey",
        "time_entries",
        type_="foreignkey",
    )
    op.drop_column("time_entries", "supervisor_user_id")
    op.alter_column(
        "time_entries",
        "supervisor_name_extracted",
        new_column_name="supervisor_name",
    )

    op.drop_index(
        "ix_ingestion_timesheets_supervisor",
        table_name="ingestion_timesheets",
    )
    op.drop_constraint(
        "ingestion_timesheets_supervisor_user_id_fkey",
        "ingestion_timesheets",
        type_="foreignkey",
    )
    op.drop_column("ingestion_timesheets", "supervisor_user_id")


def downgrade() -> None:
    import sqlalchemy as sa

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

    op.alter_column(
        "time_entries",
        "supervisor_name",
        new_column_name="supervisor_name_extracted",
    )
    op.add_column(
        "time_entries",
        sa.Column(
            "supervisor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_time_entries_supervisor",
        "time_entries",
        ["supervisor_user_id"],
    )
