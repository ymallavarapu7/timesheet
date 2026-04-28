"""Unit tests for the simplified supervisor model.

Supervisor is a free-form string for-the-record audit anchor:
  - IngestionTimesheet.extracted_supervisor_name (mutable, reviewer can edit)
  - TimeEntry.supervisor_name (carried forward at approval, then immutable)

There's no FK to User. Supervisors are typically client-side, not tenant
employees, so a User-row binding would clutter the user list. The
original LLM extraction is preserved in IngestionTimesheet.extracted_data
JSON for audit, so a single editable column on each table is enough.

Migration 037 dropped the misaimed FK columns (supervisor_user_id) from
both tables and renamed time_entries.supervisor_name_extracted to
supervisor_name. These tests pin the post-migration shape.

End-to-end behavior (PATCH the extracted name, propagate on approval) is
exercised via the Docker integration suite, not here, since the local
SQLite shim can't compile broader app fixtures.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from app.models.ingestion_timesheet import IngestionTimesheet
from app.models.time_entry import TimeEntry
from app.schemas.ingestion import (
    IngestionTimesheetDetail,
    IngestionTimesheetSummary,
    TimesheetDataUpdate,
)


def _load_migration(name: str):
    """Load a migration module without importing alembic.op."""
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / name
    src = path.read_text()
    src = src.replace("from alembic import op\n", "op = None\n")
    spec = importlib.util.spec_from_loader(f"_mig_{name}", loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(src, module.__dict__)
    return module


def test_migration_037_chains_off_036():
    mig = _load_migration("037_supervisor_simplify.py")
    assert mig.revision == "037_supervisor_simplify"
    assert mig.down_revision == "036_supervisor_persistence"


def test_ingestion_timesheet_keeps_extracted_supervisor_name():
    columns = {c.name for c in IngestionTimesheet.__table__.columns}
    assert "extracted_supervisor_name" in columns


def test_ingestion_timesheet_no_longer_has_supervisor_user_id():
    columns = {c.name for c in IngestionTimesheet.__table__.columns}
    assert "supervisor_user_id" not in columns


def test_ingestion_timesheet_no_longer_has_supervisor_relationship():
    assert "supervisor" not in IngestionTimesheet.__mapper__.relationships


def test_time_entry_has_supervisor_name_string_column():
    columns = {c.name for c in TimeEntry.__table__.columns}
    assert "supervisor_name" in columns


def test_time_entry_no_longer_has_supervisor_user_id_or_extracted():
    columns = {c.name for c in TimeEntry.__table__.columns}
    assert "supervisor_user_id" not in columns
    # The previous column was renamed; the old name should be gone.
    assert "supervisor_name_extracted" not in columns


def test_time_entry_no_longer_has_supervisor_relationship():
    assert "supervisor" not in TimeEntry.__mapper__.relationships


def test_timesheet_data_update_accepts_extracted_supervisor_name_string():
    payload = TimesheetDataUpdate(extracted_supervisor_name="Jianli Xiao")
    dumped = payload.model_dump(exclude_unset=True)
    assert dumped == {"extracted_supervisor_name": "Jianli Xiao"}


def test_timesheet_data_update_accepts_clearing_supervisor():
    payload = TimesheetDataUpdate(extracted_supervisor_name=None)
    dumped = payload.model_dump(exclude_unset=True)
    assert dumped == {"extracted_supervisor_name": None}


def test_timesheet_data_update_omits_supervisor_when_not_set():
    # When the reviewer edits only client_id, supervisor must not appear
    # in the update payload — leave the existing value alone.
    payload = TimesheetDataUpdate(client_id=7)
    dumped = payload.model_dump(exclude_unset=True)
    assert "extracted_supervisor_name" not in dumped


def test_timesheet_data_update_drops_supervisor_user_id_field():
    """The FK field should no longer exist on the schema. If it sneaks
    back in, this fails so we catch it before re-shipping the wrong
    model."""
    fields = TimesheetDataUpdate.model_fields
    assert "supervisor_user_id" not in fields


def test_summary_schema_no_longer_exposes_supervisor_user_id():
    fields = IngestionTimesheetSummary.model_fields
    assert "extracted_supervisor_name" in fields
    assert "supervisor_user_id" not in fields
    assert "supervisor_name" not in fields


def test_detail_schema_no_longer_exposes_supervisor_user_id():
    fields = IngestionTimesheetDetail.model_fields
    assert "extracted_supervisor_name" in fields
    assert "supervisor_user_id" not in fields
    assert "supervisor_name" not in fields
