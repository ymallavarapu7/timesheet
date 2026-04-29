"""Catch up alembic with columns that exist on the live shared DB

Revision ID: 038_schema_drift_catchup
Revises: 037_supervisor_simplify
Create Date: 2026-04-29

While preparing the per-tenant database split (Phase 3.C), we discovered
that `timesheet_db` (the live shared dev database) carries two columns
that no alembic migration adds. They were applied at some point outside
the alembic tree, presumably via a hand-edit or the legacy
`_backfill_legacy_schema` helper in `app/db.py`.

When we provisioned a fresh `acufy_tenant_<slug>` database via
`alembic upgrade head` and then tried to copy rows from `timesheet_db`,
the INSERT failed with `UndefinedColumnError` because the source had
columns the target lacked. Both columns ARE present on the SQLAlchemy
models, so the model and live DB agreed; only the migration tree was
behind.

The drift, found by joining `information_schema.columns` between live
and fresh:

  - `users.timezone` VARCHAR(64) NULL DEFAULT 'UTC'
    Model: `app/models/user.py:36`
  - `ingestion_timesheets.extracted_supervisor_name` VARCHAR(255) NULL
    Model: `app/models/ingestion_timesheet.py:71`

This migration brings fresh tenant DBs in line with the model. It is
idempotent: on `timesheet_db` the columns already exist and the IF NOT
EXISTS guards make this a no-op. On a freshly bootstrapped tenant DB
the columns get added.

The 28 server-side default mismatches that also showed up in the diff
(e.g., `is_active boolean DEFAULT true`) are cosmetic for our data
migration purposes (INSERT supplies all values explicitly) and are not
addressed here. They can be reconciled in a follow-up if we want
parity for future model-level inserts.
"""
from alembic import op


revision = "038_schema_drift_catchup"
down_revision = "037_supervisor_simplify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) DEFAULT 'UTC'"
    )
    op.execute(
        "ALTER TABLE ingestion_timesheets "
        "ADD COLUMN IF NOT EXISTS extracted_supervisor_name VARCHAR(255)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ingestion_timesheets "
        "DROP COLUMN IF EXISTS extracted_supervisor_name"
    )
    op.execute(
        "ALTER TABLE users DROP COLUMN IF EXISTS timezone"
    )
