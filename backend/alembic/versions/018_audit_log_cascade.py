"""Add ON DELETE CASCADE to ingestion_audit_log.ingestion_timesheet_id FK

Revision ID: 018_audit_log_cascade
Revises: 017_ingestion_cascade
Create Date: 2026-04-08
"""
from alembic import op

revision = "018_audit_log_cascade"
down_revision = "017_ingestion_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ingestion_audit_log_ingestion_timesheet_id_fkey",
        "ingestion_audit_log",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "ingestion_audit_log_ingestion_timesheet_id_fkey",
        "ingestion_audit_log", "ingestion_timesheets",
        ["ingestion_timesheet_id"], ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ingestion_audit_log_ingestion_timesheet_id_fkey",
        "ingestion_audit_log",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "ingestion_audit_log_ingestion_timesheet_id_fkey",
        "ingestion_audit_log", "ingestion_timesheets",
        ["ingestion_timesheet_id"], ["id"],
    )
