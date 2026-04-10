from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.crud.time_entry import (
    approve_time_entry,
    create_time_entry,
    list_pending_approvals,
    list_user_entries,
    reject_time_entry,
    submit_time_entries,
    update_time_entry,
)
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.schemas import TimeEntryCreate, TimeEntryUpdate


@pytest.mark.asyncio
async def test_create_time_entry_defaults_to_draft(db_session, seeded_data):
    employee = seeded_data["employee"]
    project = seeded_data["project"]
    today = date.today()

    created_entry = await create_time_entry(
        db_session,
        employee.id,
        employee.tenant_id,
        TimeEntryCreate(
            project_id=project.id,
            entry_date=today,
            hours=Decimal("3.50"),
            description="Created by unit test",
        ),
    )

    assert created_entry.id is not None
    assert created_entry.status == TimeEntryStatus.DRAFT
    assert created_entry.user_id == employee.id


@pytest.mark.asyncio
async def test_update_time_entry_allows_only_draft(db_session, seeded_data):
    draft_entry = seeded_data["draft_entry"]
    submitted_entry = seeded_data["submitted_entry"]

    updated = await update_time_entry(
        db_session,
        draft_entry,
        TimeEntryUpdate(
            hours=Decimal("9.00"),
            description="Updated description",
            edit_reason="Correction",
            history_summary="Adjusted hours and details",
        ),
        edited_by=seeded_data["employee"].id,
    )
    assert updated.hours == Decimal("9.00")
    assert updated.description == "Updated description"

    with pytest.raises(ValueError, match="Can only update DRAFT or REJECTED time entries"):
        await update_time_entry(
            db_session,
            submitted_entry,
            TimeEntryUpdate(description="Should fail"),
            edited_by=seeded_data["employee"].id,
        )


@pytest.mark.asyncio
async def test_submit_approve_and_reject_workflow(db_session, seeded_data):
    employee = seeded_data["employee"]
    manager = seeded_data["manager"]
    submitted_entry = seeded_data["submitted_entry"]

    this_week_monday = date.today() - timedelta(days=date.today().weekday())
    last_week_workday = this_week_monday - timedelta(days=3)
    submit_candidate = TimeEntry(
        user_id=employee.id,
        tenant_id=seeded_data["employee"].tenant_id,
        project_id=seeded_data["project"].id,
        entry_date=last_week_workday,
        hours=Decimal("4.00"),
        description="Prior week draft",
        status=TimeEntryStatus.DRAFT,
    )
    db_session.add(submit_candidate)
    await db_session.commit()
    await db_session.refresh(submit_candidate)

    submitted = await submit_time_entries(db_session, employee.id, [submit_candidate.id])
    assert len(submitted) == 1
    assert submitted[0].status == TimeEntryStatus.SUBMITTED

    approved = await approve_time_entry(db_session, submitted_entry.id, manager.id)
    assert approved.status == TimeEntryStatus.APPROVED
    assert approved.approved_by == manager.id

    rejected = await reject_time_entry(db_session, submitted[0].id, manager.id, "Needs more detail")
    assert rejected.status == TimeEntryStatus.REJECTED
    assert rejected.rejection_reason == "Needs more detail"


@pytest.mark.asyncio
async def test_list_queries_include_relationships(db_session, seeded_data):
    employee = seeded_data["employee"]

    user_entries = await list_user_entries(db_session, employee.id)
    assert len(user_entries) >= 1
    assert all(entry.user is not None for entry in user_entries)
    assert all(entry.project is not None for entry in user_entries)

    pending = await list_pending_approvals(db_session, manager_ids=[1])
    assert len(pending) >= 1
    assert all(entry.user is not None for entry in pending)
    assert all(entry.project is not None for entry in pending)
