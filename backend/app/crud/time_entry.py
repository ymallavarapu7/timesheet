from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import asc, desc, func, or_
from sqlalchemy.exc import IntegrityError
from decimal import Decimal
from app.models.time_entry import TimeEntry, TimeEntryEditHistory, TimeEntryStatus
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.tenant_settings import TenantSettings
from app.core.config import settings
from app.schemas import TimeEntryCreate, TimeEntryUpdate
from typing import Optional
from datetime import date, datetime, timedelta, timezone


async def _future_entries_allowed(db: AsyncSession, tenant_id: int) -> bool:
    result = await db.execute(
        select(TenantSettings.value).where(
            TenantSettings.tenant_id == tenant_id,
            TenantSettings.key == "allow_future_entries",
        )
    )
    value = result.scalar_one_or_none()
    return str(value).lower() == "true" if value is not None else False


async def get_time_entry_by_id(db: AsyncSession, entry_id: int, tenant_id: Optional[int] = None) -> Optional[TimeEntry]:
    """Get time entry by ID, scoped to a tenant. Pass tenant_id=None only for PLATFORM_ADMIN."""
    query = select(TimeEntry).where(TimeEntry.id == entry_id)
    if tenant_id is not None:
        query = query.where(TimeEntry.tenant_id == tenant_id)
    query = query.options(
        selectinload(TimeEntry.user).selectinload(User.manager_assignment),
        selectinload(TimeEntry.user).selectinload(User.project_access),
        selectinload(TimeEntry.project),
        selectinload(TimeEntry.task),
    )
    result = await db.execute(query)
    return result.scalars().first()


async def get_time_entries_by_ids(db: AsyncSession, entry_ids: list[int], tenant_id: Optional[int] = None) -> list[TimeEntry]:
    if not entry_ids:
        return []

    query = select(TimeEntry).where(TimeEntry.id.in_(entry_ids))
    if tenant_id is not None:
        query = query.where(TimeEntry.tenant_id == tenant_id)
    query = query.options(
        selectinload(TimeEntry.user).selectinload(User.manager_assignment),
        selectinload(TimeEntry.user).selectinload(User.project_access),
        selectinload(TimeEntry.project),
        selectinload(TimeEntry.task),
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_time_entry(db: AsyncSession, user_id: int, tenant_id: int, entry_create: TimeEntryCreate) -> TimeEntry:
    """Create a new time entry."""
    # Enforce backdate limit
    max_backdate = date.today() - timedelta(weeks=settings.time_entry_backdate_weeks)
    if entry_create.entry_date < max_backdate:
        raise ValueError(
            f"Cannot create entries more than {settings.time_entry_backdate_weeks} weeks in the past"
        )
    if entry_create.entry_date > date.today() and not await _future_entries_allowed(db, tenant_id):
        raise ValueError("Cannot create entries for future dates")

    await _validate_hours_constraints(
        db,
        user_id=user_id,
        entry_date=entry_create.entry_date,
        hours=entry_create.hours,
    )
    await _validate_task_selection(
        db,
        project_id=entry_create.project_id,
        task_id=entry_create.task_id,
    )

    db_entry = TimeEntry(
        user_id=user_id,
        tenant_id=tenant_id,
        created_by=user_id,
        updated_by=user_id,
        **entry_create.model_dump()
    )
    db.add(db_entry)
    try:
        await db.commit()
        await db.refresh(db_entry)
    except IntegrityError:
        await db.rollback()
        raise
    return db_entry


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _last_working_day_for_week(value: date) -> date:
    return _week_start(value) + timedelta(days=4)


async def _validate_hours_constraints(
    db: AsyncSession,
    user_id: int,
    entry_date: date,
    hours: Decimal,
    exclude_entry_id: Optional[int] = None,
) -> None:
    entry_hours = Decimal(str(hours))
    max_hours_per_entry = Decimal(str(settings.max_hours_per_entry))
    max_hours_per_day = Decimal(str(settings.max_hours_per_day))
    max_hours_per_week = Decimal(str(settings.max_hours_per_week))

    if entry_hours > max_hours_per_entry:
        raise ValueError(
            f"Hours per entry cannot exceed {settings.max_hours_per_entry:g}"
        )

    daily_query = select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(
        (TimeEntry.user_id == user_id)
        & (TimeEntry.entry_date == entry_date)
        & (TimeEntry.status != TimeEntryStatus.REJECTED)
    )
    if exclude_entry_id is not None:
        daily_query = daily_query.where(TimeEntry.id != exclude_entry_id)

    daily_existing_total = Decimal(str((await db.scalar(daily_query)) or 0))
    if daily_existing_total + entry_hours > max_hours_per_day:
        raise ValueError(
            f"Daily total hours cannot exceed {settings.max_hours_per_day:g}"
        )

    week_start = _week_start(entry_date)
    week_end = week_start + timedelta(days=6)
    weekly_query = select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(
        (TimeEntry.user_id == user_id)
        & (TimeEntry.entry_date >= week_start)
        & (TimeEntry.entry_date <= week_end)
        & (TimeEntry.status != TimeEntryStatus.REJECTED)
    )
    if exclude_entry_id is not None:
        weekly_query = weekly_query.where(TimeEntry.id != exclude_entry_id)

    weekly_existing_total = Decimal(str((await db.scalar(weekly_query)) or 0))
    if weekly_existing_total + entry_hours > max_hours_per_week:
        raise ValueError(
            f"Weekly total hours cannot exceed {settings.max_hours_per_week:g}"
        )


async def _validate_task_selection(
    db: AsyncSession,
    project_id: int,
    task_id: Optional[int],
) -> None:
    if task_id is None:
        return

    result = await db.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalars().first()
    if not task:
        raise ValueError("Selected task not found")
    if not task.is_active:
        raise ValueError("Selected task is inactive")
    if task.project_id != project_id:
        raise ValueError("Selected task does not belong to selected project")


async def update_time_entry(
    db: AsyncSession,
    entry: TimeEntry,
    entry_update: TimeEntryUpdate,
    edited_by: int,
) -> TimeEntry:
    """Update time entry (DRAFT or REJECTED entries). REJECTED entries transition back to DRAFT."""
    if entry.status not in (TimeEntryStatus.DRAFT, TimeEntryStatus.REJECTED):
        raise ValueError("Can only update DRAFT or REJECTED time entries")

    update_data = entry_update.model_dump(exclude_unset=True)
    edit_reason = (update_data.pop("edit_reason", None) or "").strip()
    history_summary = (update_data.pop("history_summary", None) or "").strip()
    if not edit_reason:
        raise ValueError("Edit reason is required")
    if not history_summary:
        raise ValueError("History summary is required")

    target_entry_date = update_data.get("entry_date", entry.entry_date)
    target_hours = update_data.get("hours", entry.hours)
    target_project_id = update_data.get("project_id", entry.project_id)
    target_task_id = update_data.get("task_id", entry.task_id)

    max_backdate = date.today() - timedelta(weeks=settings.time_entry_backdate_weeks)
    if target_entry_date < max_backdate:
        raise ValueError(
            f"Cannot set entry date more than {settings.time_entry_backdate_weeks} weeks in the past"
        )
    if target_entry_date > date.today() and not await _future_entries_allowed(db, entry.tenant_id):
        raise ValueError("Cannot set entry date to a future date")

    await _validate_hours_constraints(
        db,
        user_id=entry.user_id,
        entry_date=target_entry_date,
        hours=target_hours,
        exclude_entry_id=entry.id,
    )
    await _validate_task_selection(
        db,
        project_id=target_project_id,
        task_id=target_task_id,
    )

    db.add(
        TimeEntryEditHistory(
            time_entry_id=entry.id,
            edited_by=edited_by,
            edited_at=datetime.now(timezone.utc),
            edit_reason=edit_reason,
            history_summary=history_summary,
            previous_project_id=entry.project_id,
            previous_entry_date=entry.entry_date,
            previous_hours=entry.hours,
            previous_description=entry.description,
        )
    )

    for field, value in update_data.items():
        setattr(entry, field, value)

    # If editing a REJECTED entry, transition it back to DRAFT so it can be resubmitted.
    if entry.status == TimeEntryStatus.REJECTED:
        entry.status = TimeEntryStatus.DRAFT
        entry.rejection_reason = None
        entry.approved_by = None
        entry.approved_at = None

    entry.last_edit_reason = edit_reason
    entry.last_history_summary = history_summary
    entry.updated_by = edited_by

    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def delete_time_entry(db: AsyncSession, entry_id: int, tenant_id: Optional[int] = None) -> bool:
    """Delete time entry (only DRAFT entries), scoped to a tenant."""
    entry = await get_time_entry_by_id(db, entry_id, tenant_id=tenant_id)
    if entry and entry.status == TimeEntryStatus.DRAFT:
        await db.delete(entry)
        await db.commit()
        return True
    return False


async def list_user_entries(
    db: AsyncSession,
    user_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[TimeEntryStatus] = None,
    search: Optional[str] = None,
    sort_by: str = "entry_date",
    sort_order: str = "desc",
    skip: int = 0,
    limit: int = 100,
) -> list[TimeEntry]:
    """List time entries for a user with optional filters."""
    query = select(TimeEntry).where(TimeEntry.user_id == user_id)

    # Eagerly load relationships
    query = query.options(
        selectinload(TimeEntry.user).selectinload(User.manager_assignment),
        selectinload(TimeEntry.user).selectinload(User.project_access),
        selectinload(TimeEntry.project),
        selectinload(TimeEntry.task),
    )

    if start_date:
        query = query.where(TimeEntry.entry_date >= start_date)
    if end_date:
        query = query.where(TimeEntry.entry_date <= end_date)
    if status:
        query = query.where(TimeEntry.status == status)

    if search:
        like = f"%{search.strip()}%"
        query = query.join(Project, Project.id == TimeEntry.project_id).where(
            or_(
                TimeEntry.description.ilike(like),
                Project.name.ilike(like),
            )
        )

    sort_map = {
        "entry_date": TimeEntry.entry_date,
        "created_at": TimeEntry.created_at,
        "hours": TimeEntry.hours,
        "status": TimeEntry.status,
    }
    sort_column = sort_map.get(sort_by, TimeEntry.entry_date)
    query = query.order_by(asc(sort_column) if sort_order ==
                           "asc" else desc(sort_column))

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def list_tenant_entries(
    db: AsyncSession,
    tenant_id: int,
    user_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[TimeEntryStatus] = None,
    sort_by: str = "entry_date",
    sort_order: str = "desc",
    skip: int = 0,
    limit: int = 200,
) -> list[TimeEntry]:
    """List time entries across the entire tenant. Admin/manager use only."""
    query = select(TimeEntry).where(TimeEntry.tenant_id == tenant_id)
    query = query.options(
        selectinload(TimeEntry.user),
        selectinload(TimeEntry.project),
        selectinload(TimeEntry.task),
    )
    if user_id is not None:
        query = query.where(TimeEntry.user_id == user_id)
    if start_date:
        query = query.where(TimeEntry.entry_date >= start_date)
    if end_date:
        query = query.where(TimeEntry.entry_date <= end_date)
    if status:
        query = query.where(TimeEntry.status == status)

    sort_map = {
        "entry_date": TimeEntry.entry_date,
        "created_at": TimeEntry.created_at,
        "hours": TimeEntry.hours,
        "status": TimeEntry.status,
    }
    sort_column = sort_map.get(sort_by, TimeEntry.entry_date)
    query = query.order_by(asc(sort_column) if sort_order == "asc" else desc(sort_column))
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def submit_time_entries(
    db: AsyncSession,
    user_id: int,
    entry_ids: list[int],
) -> list[TimeEntry]:
    """Submit multiple time entries for approval."""
    # Get all entries with relationships loaded
    query = select(TimeEntry).where(
        (TimeEntry.user_id == user_id) &
        (TimeEntry.id.in_(entry_ids)) &
        (TimeEntry.status == TimeEntryStatus.DRAFT)
    )
    query = query.options(
        selectinload(TimeEntry.user).selectinload(User.manager_assignment),
        selectinload(TimeEntry.user).selectinload(User.project_access),
        selectinload(TimeEntry.project),
        selectinload(TimeEntry.task),
    )
    result = await db.execute(query)
    entries = result.scalars().all()

    if not entries:
        raise ValueError("No DRAFT entries found to submit")

    today = date.today()
    requested_ids = {entry.id for entry in entries}
    week_starts = {_week_start(entry.entry_date) for entry in entries}

    for week_start in week_starts:
        week_end = week_start + timedelta(days=4)
        week_end_calendar = week_start + timedelta(days=6)
        if today < week_end:
            raise ValueError(
                f"Weekly entry submission for week ending {week_end.isoformat()} is allowed on or after the last working day"
            )

        week_entries = [entry for entry in entries if _week_start(
            entry.entry_date) == week_start]
        week_requested_ids = {entry.id for entry in week_entries}

        full_week_query = select(TimeEntry.id).where(
            (TimeEntry.user_id == user_id)
            & (TimeEntry.status == TimeEntryStatus.DRAFT)
            & (TimeEntry.entry_date >= week_start)
            & (TimeEntry.entry_date <= week_end_calendar)
        )
        full_week_result = await db.execute(full_week_query)
        full_week_ids = set(full_week_result.scalars().all())
        if week_requested_ids != full_week_ids:
            missing_ids = sorted(list(full_week_ids - requested_ids))
            raise ValueError(
                f"Submit all draft entries for the week ending {week_end.isoformat()} together. Missing entry ids: {missing_ids}"
            )

        weekly_total = Decimal(str((await db.scalar(
            select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(
                (TimeEntry.user_id == user_id)
                & (TimeEntry.entry_date >= week_start)
                & (TimeEntry.entry_date <= week_start + timedelta(days=6))
                & (TimeEntry.status != TimeEntryStatus.REJECTED)
            )
        )) or 0))

        minimum_weekly_hours = Decimal(str(settings.min_submit_weekly_hours))
        if weekly_total < minimum_weekly_hours:
            raise ValueError(
                f"Cannot submit week ending {week_end.isoformat()} because weekly hours are below minimum required ({settings.min_submit_weekly_hours:g})"
            )

    # Update status
    for entry in entries:
        entry.status = TimeEntryStatus.SUBMITTED
        entry.submitted_at = datetime.now(timezone.utc)
        entry.updated_by = user_id
        db.add(entry)

    await db.commit()

    # Refresh all entries
    for entry in entries:
        await db.refresh(entry)

    return entries


async def get_weekly_submission_status(db: AsyncSession, user_id: int) -> tuple[bool, str | None, date]:
    today = date.today()
    due_date = _last_working_day_for_week(today)
    if today < due_date:
        return False, f"Weekly entry submission opens on {due_date.isoformat()}", due_date

    week_start = _week_start(today)
    draft_count = await db.scalar(
        select(func.count(TimeEntry.id)).where(
            (TimeEntry.user_id == user_id)
            & (TimeEntry.status == TimeEntryStatus.DRAFT)
            & (TimeEntry.entry_date >= week_start)
            & (TimeEntry.entry_date <= due_date)
        )
    )
    if int(draft_count or 0) == 0:
        return False, "No draft entries available for this week", due_date

    return True, None, due_date


async def list_pending_approvals(
    db: AsyncSession,
    employee_ids: Optional[list[int]] = None,
    manager_ids: Optional[list[int]] = None,
    tenant_id: Optional[int] = None,
    search: Optional[str] = None,
    sort_by: str = "entry_date",
    sort_order: str = "desc",
    skip: int = 0,
    limit: int = 100,
) -> list[TimeEntry]:
    """
    List submitted time entries for managers to approve.
    This is a simplified version - ideally would have team assignment logic.
    """
    # Backward compatibility: historical callers passed manager_ids, but that
    # parameter never actually filtered results.
    _ = manager_ids

    query = select(TimeEntry).where(
        TimeEntry.status == TimeEntryStatus.SUBMITTED)
    if tenant_id is not None:
        query = query.where(TimeEntry.tenant_id == tenant_id)
    if employee_ids is not None:
        if not employee_ids:
            return []
        query = query.where(TimeEntry.user_id.in_(employee_ids))
    query = query.options(
        selectinload(TimeEntry.user),
        selectinload(TimeEntry.project),
        selectinload(TimeEntry.task),
    )
    joined_user = False

    if search:
        like = f"%{search.strip()}%"
        query = query.join(User, User.id == TimeEntry.user_id).join(Project, Project.id == TimeEntry.project_id).where(
            or_(
                TimeEntry.description.ilike(like),
                User.full_name.ilike(like),
                Project.name.ilike(like),
            )
        )
        joined_user = True

    sort_map = {
        "entry_date": TimeEntry.entry_date,
        "submitted_at": TimeEntry.submitted_at,
        "hours": TimeEntry.hours,
        "employee": User.full_name,
    }

    if sort_by == "employee" and not joined_user:
        query = query.join(User, User.id == TimeEntry.user_id)

    sort_column = sort_map.get(sort_by, TimeEntry.entry_date)
    query = query.order_by(asc(sort_column) if sort_order ==
                           "asc" else desc(sort_column))

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def approve_time_entry(
    db: AsyncSession,
    entry_id: int,
    approved_by_id: int,
    tenant_id: Optional[int] = None,
) -> TimeEntry:
    """Approve a time entry."""
    entry = await get_time_entry_by_id(db, entry_id, tenant_id=tenant_id)
    if not entry:
        raise ValueError("Time entry not found")

    if entry.status != TimeEntryStatus.SUBMITTED:
        raise ValueError("Can only approve SUBMITTED entries")

    entry.status = TimeEntryStatus.APPROVED
    entry.approved_by = approved_by_id
    entry.approved_at = datetime.now(timezone.utc)
    entry.rejection_reason = None
    entry.updated_by = approved_by_id

    db.add(entry)
    await db.commit()

    # Re-fetch with relationships loaded
    return await get_time_entry_by_id(db, entry_id, tenant_id=tenant_id)


async def approve_time_entries_batch(
    db: AsyncSession,
    entry_ids: list[int],
    approved_by_id: int,
    tenant_id: Optional[int] = None,
) -> list[TimeEntry]:
    entries = await get_time_entries_by_ids(db, entry_ids, tenant_id=tenant_id)
    if len(entries) != len(set(entry_ids)):
        raise ValueError("One or more time entries were not found")

    if any(entry.status != TimeEntryStatus.SUBMITTED for entry in entries):
        raise ValueError("Can only approve SUBMITTED entries")

    approved_at = datetime.now(timezone.utc)
    for entry in entries:
        entry.status = TimeEntryStatus.APPROVED
        entry.approved_by = approved_by_id
        entry.approved_at = approved_at
        entry.rejection_reason = None
        entry.updated_by = approved_by_id
        db.add(entry)

    await db.commit()
    return await get_time_entries_by_ids(db, entry_ids, tenant_id=tenant_id)


async def reject_time_entry(
    db: AsyncSession,
    entry_id: int,
    approved_by_id: int,
    rejection_reason: str,
    tenant_id: Optional[int] = None,
) -> TimeEntry:
    """Reject a time entry."""
    entry = await get_time_entry_by_id(db, entry_id, tenant_id=tenant_id)
    if not entry:
        raise ValueError("Time entry not found")

    if entry.status != TimeEntryStatus.SUBMITTED:
        raise ValueError("Can only reject SUBMITTED entries")

    entry.status = TimeEntryStatus.REJECTED
    entry.approved_by = approved_by_id
    entry.approved_at = datetime.now(timezone.utc)
    entry.rejection_reason = rejection_reason
    entry.updated_by = approved_by_id

    db.add(entry)
    await db.commit()

    # Re-fetch with relationships loaded
    return await get_time_entry_by_id(db, entry_id, tenant_id=tenant_id)


async def reject_time_entries_batch(
    db: AsyncSession,
    entry_ids: list[int],
    rejected_by_id: int,
    rejection_reason: str,
    tenant_id: Optional[int] = None,
) -> list[TimeEntry]:
    entries = await get_time_entries_by_ids(db, entry_ids, tenant_id=tenant_id)
    if len(entries) != len(set(entry_ids)):
        raise ValueError("One or more time entries were not found")

    if any(entry.status != TimeEntryStatus.SUBMITTED for entry in entries):
        raise ValueError("Can only reject SUBMITTED entries")

    rejected_at = datetime.now(timezone.utc)
    for entry in entries:
        entry.status = TimeEntryStatus.REJECTED
        entry.approved_by = rejected_by_id
        entry.approved_at = rejected_at
        entry.rejection_reason = rejection_reason
        entry.updated_by = rejected_by_id
        db.add(entry)

    await db.commit()
    return await get_time_entries_by_ids(db, entry_ids, tenant_id=tenant_id)
