"""Unit tests for the editable + persisted Supervisor work.

These tests cover the static / pure-Python pieces:
  - Migration 036 declares the right revision chain.
  - ORM models expose the new columns and relationships.
  - TimesheetDataUpdate schema accepts supervisor_user_id.

The full end-to-end behavior (cascade through approval, fuzzy-match on
ingestion, validator behavior) is exercised via the Docker integration
suite — the local SQLite shim can't compile some of the JSONB columns
used by the broader app fixtures (project_env_quirk).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.models.ingestion_timesheet import IngestionTimesheet
from app.models.time_entry import TimeEntry
from app.schemas.ingestion import (
    IngestionTimesheetDetail,
    IngestionTimesheetSummary,
    TimesheetDataUpdate,
)


def _load_migration():
    """Load 036_supervisor_persistence.py without importing alembic.op."""
    path = (
        Path(__file__).resolve().parent.parent
        / "alembic" / "versions" / "036_supervisor_persistence.py"
    )
    src = path.read_text()
    # Strip the alembic.op import so the module can be loaded standalone;
    # we only care about the declarative metadata at module top, not the
    # upgrade()/downgrade() bodies.
    src = src.replace("from alembic import op\n", "op = None\n")
    spec = importlib.util.spec_from_loader("_mig036", loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(src, module.__dict__)
    return module


def test_migration_chains_off_035():
    mig = _load_migration()
    assert mig.revision == "036_supervisor_persistence"
    assert mig.down_revision == "035_client_email_domains"


def test_ingestion_timesheet_model_has_supervisor_user_id():
    columns = {c.name for c in IngestionTimesheet.__table__.columns}
    assert "supervisor_user_id" in columns
    # The legacy free-string field stays as-is for audit.
    assert "extracted_supervisor_name" in columns


def test_ingestion_timesheet_supervisor_relationship_is_to_user():
    rel = IngestionTimesheet.__mapper__.relationships["supervisor"]
    assert rel.argument == "User"


def test_ingestion_timesheet_supervisor_user_id_has_index():
    # Index supports future "show me all timesheets I supervised" reports.
    indexed_cols = set()
    for index in IngestionTimesheet.__table__.indexes:
        for col in index.columns:
            indexed_cols.add(col.name)
    # Column-level index=True attaches to the column itself, not as a
    # named Index. Check both.
    col = IngestionTimesheet.__table__.columns["supervisor_user_id"]
    assert col.index or "supervisor_user_id" in indexed_cols


def test_time_entry_model_has_supervisor_columns():
    columns = {c.name for c in TimeEntry.__table__.columns}
    assert "supervisor_user_id" in columns
    assert "supervisor_name_extracted" in columns


def test_time_entry_supervisor_relationship_is_to_user():
    rel = TimeEntry.__mapper__.relationships["supervisor"]
    assert rel.argument == "User"


def test_timesheet_data_update_accepts_supervisor_user_id():
    payload = TimesheetDataUpdate(supervisor_user_id=42)
    dumped = payload.model_dump(exclude_unset=True)
    assert dumped == {"supervisor_user_id": 42}


def test_timesheet_data_update_accepts_supervisor_user_id_none():
    # Reviewer clearing the supervisor (e.g. document didn't have one).
    payload = TimesheetDataUpdate(supervisor_user_id=None)
    dumped = payload.model_dump(exclude_unset=True)
    assert dumped == {"supervisor_user_id": None}


def test_timesheet_data_update_omits_supervisor_when_not_set():
    # When the reviewer edits, say, only client_id, supervisor_user_id
    # should not be included in exclude_unset dump (so the existing
    # supervisor stays untouched on the model).
    payload = TimesheetDataUpdate(client_id=7)
    dumped = payload.model_dump(exclude_unset=True)
    assert "supervisor_user_id" not in dumped


def test_summary_schema_exposes_supervisor_fields():
    fields = IngestionTimesheetSummary.model_fields
    assert "supervisor_user_id" in fields
    assert "supervisor_name" in fields
    # extracted_supervisor_name is the audit anchor; must not be removed.
    assert "extracted_supervisor_name" in fields


def test_detail_schema_exposes_supervisor_fields():
    fields = IngestionTimesheetDetail.model_fields
    assert "supervisor_user_id" in fields
    assert "supervisor_name" in fields
    assert "extracted_supervisor_name" in fields
