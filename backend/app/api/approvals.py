from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, get_tenant_db, require_role
from app.services.notification_emails import notify_timesheet_approved, notify_timesheet_rejected
from app.services.activity import (
    TENANT_ADMIN_ACTIVITY_SCOPE,
    build_activity_event,
    record_activity_events,
)
from app.crud.time_entry import (
    approve_time_entries_batch,
    approve_time_entry,
    get_time_entries_by_ids,
    get_time_entry_by_id,
    list_pending_approvals,
    reject_time_entries_batch,
    reject_time_entry,
)
from app.schemas import (
    TimeEntryBatchApproveRequest,
    TimeEntryBatchRejectRequest,
    TimeEntryResponse,
    TimeEntryApproveRequest,
    TimeEntryRejectRequest,
    TimeEntryWithUser,
)
from app.models.assignments import EmployeeManagerAssignment
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.user import User
from app.services.quickbooks import get_quickbooks_service

router = APIRouter(prefix="/approvals", tags=["approvals"])
APPROVAL_HISTORY_TTL_DAYS = 7


async def _get_direct_report_ids(db: AsyncSession, manager_user_id: int) -> list[int]:
    result = await db.execute(
        select(EmployeeManagerAssignment.employee_id)
        .where(EmployeeManagerAssignment.manager_id == manager_user_id)
    )
    return list(result.scalars().all())


def _week_start(value: date, week_start_day: int = 0) -> date:
    """0=Sunday, 1=Monday."""
    py_weekday = value.weekday()  # 0=Mon..6=Sun
    offset = (py_weekday + 1) % 7 if week_start_day == 0 else py_weekday
    return value - timedelta(days=offset)


async def _resolve_week_start_day(db: AsyncSession, tenant_id: int) -> int:
    from app.crud.time_entry import _tenant_week_start_day
    return await _tenant_week_start_day(db, tenant_id)


async def _validate_weekly_batch(
    db: AsyncSession,
    current_user: User,
    entries: list[TimeEntry],
) -> None:
    if not entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No time entries were provided",
        )

    user_ids = {entry.user_id for entry in entries}

    # Verify all entries belong to the current user's tenant
    entry_tenant_ids = {entry.tenant_id for entry in entries}
    if current_user.tenant_id is not None and entry_tenant_ids != {current_user.tenant_id}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot approve entries from a different tenant",
        )

    if current_user.role.value != "CEO":
        direct_report_ids = set(await _get_direct_report_ids(db, current_user.id))
        if not user_ids.issubset(direct_report_ids):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only review entries for your direct reports",
            )

    if len(user_ids) != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Weekly approval must target one employee at a time",
        )

    wsd = await _resolve_week_start_day(db, current_user.tenant_id)
    week_starts = {_week_start(entry.entry_date, wsd) for entry in entries}
    if len(week_starts) != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Weekly approval must target one work week at a time",
        )

    employee_id = entries[0].user_id
    week_start = next(iter(week_starts))
    week_end = week_start + timedelta(days=6)
    submitted_result = await db.execute(
        select(TimeEntry.id)
        .where(TimeEntry.user_id == employee_id)
        .where(TimeEntry.status == TimeEntryStatus.SUBMITTED)
        .where(TimeEntry.entry_date >= week_start)
        .where(TimeEntry.entry_date <= week_end)
    )
    submitted_ids = set(submitted_result.scalars().all())
    requested_ids = {entry.id for entry in entries}
    if requested_ids != submitted_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Approve or reject all submitted entries for the selected week together",
        )


@router.get("/pending", response_model=list[TimeEntryWithUser])
async def get_pending_approvals(
    search: str | None = Query(None),
    sort_by: str = Query(
        "entry_date", pattern="^(entry_date|submitted_at|hours|employee)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role(
        "MANAGER", "SENIOR_MANAGER", "CEO")),
) -> list:
    """
    Get pending time entries for approval (Manager/Senior Manager/CEO only).
    """
    employee_ids = None
    if current_user.role.value != "CEO":
        assigned_employee_ids = await _get_direct_report_ids(db, current_user.id)
        employee_ids = assigned_employee_ids or []

    return await list_pending_approvals(
        db,
        employee_ids=employee_ids,
        tenant_id=current_user.tenant_id,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )


@router.get("/history", response_model=list[TimeEntryWithUser])
async def get_approval_history(
    search: str | None = Query(None),
    sort_by: str = Query(
        "approved_at", pattern="^(approved_at|entry_date|hours|employee|status)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    include_older: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role(
        "MANAGER", "SENIOR_MANAGER", "CEO")),
) -> list[TimeEntry]:
    employee_ids = None
    if current_user.role.value != "CEO":
        assigned_employee_ids = await _get_direct_report_ids(db, current_user.id)
        employee_ids = assigned_employee_ids or []

    query = (
        select(TimeEntry)
        .options(
            selectinload(TimeEntry.user),
            selectinload(TimeEntry.project),
            selectinload(TimeEntry.task),
        )
        .where(TimeEntry.status.in_([TimeEntryStatus.APPROVED, TimeEntryStatus.REJECTED]))
        .where(TimeEntry.tenant_id == current_user.tenant_id)
    )

    if employee_ids is not None:
        if not employee_ids:
            return []
        query = query.where(TimeEntry.user_id.in_(employee_ids))

    if not include_older:
        cutoff = datetime.now(timezone.utc) - timedelta(days=APPROVAL_HISTORY_TTL_DAYS)
        query = query.where(TimeEntry.updated_at >= cutoff)

    joined_user = False
    if search:
        search_value = f"%{search.strip()}%"
        query = query.join(TimeEntry.user).join(TimeEntry.project).where(
            or_(
                User.full_name.ilike(search_value),
                TimeEntry.description.ilike(search_value),
                TimeEntry.rejection_reason.ilike(search_value),
            )
        )
        joined_user = True

    sort_column_map = {
        "approved_at": TimeEntry.approved_at,
        "entry_date": TimeEntry.entry_date,
        "hours": TimeEntry.hours,
        "employee": User.full_name,
        "status": TimeEntry.status,
    }
    sort_column = sort_column_map.get(sort_by, TimeEntry.approved_at)
    if sort_by == "employee" and not joined_user:
        query = query.join(TimeEntry.user)

    if sort_order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/history-grouped")
async def get_approval_history_grouped(
    days_back: int = Query(30, ge=1, le=365),
    status_filter: str | None = Query(None, pattern="^(approved|rejected|mixed)$"),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role(
        "MANAGER", "SENIOR_MANAGER", "CEO")),
) -> list[dict]:
    """
    Returns approval history grouped by (employee, week_start).
    Each group has summary stats and the individual entries for expansion.
    """
    employee_ids = None
    if current_user.role.value != "CEO":
        assigned_employee_ids = await _get_direct_report_ids(db, current_user.id)
        employee_ids = assigned_employee_ids or []

    cutoff = date.today() - timedelta(days=days_back)

    query = (
        select(TimeEntry)
        .options(
            selectinload(TimeEntry.user),
            selectinload(TimeEntry.project),
            selectinload(TimeEntry.task),
        )
        .where(TimeEntry.status.in_([TimeEntryStatus.APPROVED, TimeEntryStatus.REJECTED]))
        .where(TimeEntry.tenant_id == current_user.tenant_id)
        .where(TimeEntry.entry_date >= cutoff)
        .order_by(TimeEntry.entry_date.asc())
    )

    if employee_ids is not None:
        if not employee_ids:
            return []
        query = query.where(TimeEntry.user_id.in_(employee_ids))

    result = await db.execute(query)
    entries = list(result.scalars().all())

    wsd = await _resolve_week_start_day(db, current_user.tenant_id)

    # Group by (user_id, week_start)
    groups: dict[str, dict] = {}
    for entry in entries:
        ws = _week_start(entry.entry_date, wsd)
        we = ws + timedelta(days=6)
        key = f"{entry.user_id}-{ws.isoformat()}"
        if key not in groups:
            groups[key] = {
                "employee_id": entry.user_id,
                "employee_name": entry.user.full_name if entry.user else "Unknown",
                "week_start": ws.isoformat(),
                "week_end": we.isoformat(),
                "total_hours": 0.0,
                "entry_count": 0,
                "approved_count": 0,
                "rejected_count": 0,
                "status": "approved",
                "entries": [],
            }
        g = groups[key]
        g["total_hours"] += float(entry.hours)
        g["entry_count"] += 1
        if entry.status == TimeEntryStatus.APPROVED:
            g["approved_count"] += 1
        else:
            g["rejected_count"] += 1
        g["entries"].append({
            "id": entry.id,
            "entry_date": entry.entry_date.isoformat(),
            "hours": float(entry.hours),
            "description": entry.description,
            "status": entry.status.value,
            "rejection_reason": entry.rejection_reason,
            "project_name": entry.project.name if entry.project else None,
            "task_name": entry.task.name if entry.task else None,
        })

    # Determine group status
    for g in groups.values():
        if g["approved_count"] > 0 and g["rejected_count"] > 0:
            g["status"] = "mixed"
        elif g["rejected_count"] > 0:
            g["status"] = "rejected"
        else:
            g["status"] = "approved"

    result_list = sorted(
        groups.values(),
        key=lambda g: (g["employee_name"], g["week_start"]),
        reverse=False,
    )
    # Sort most recent week first per employee
    result_list = sorted(result_list, key=lambda g: (g["employee_name"], g["week_start"]), reverse=False)
    result_list.sort(key=lambda g: g["week_start"], reverse=True)

    if status_filter:
        result_list = [g for g in result_list if g["status"] == status_filter]

    return result_list


@router.post("/batch-approve", response_model=list[TimeEntryResponse])
async def approve_entry_batch(
    approve_request: TimeEntryBatchApproveRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role(
        "MANAGER", "SENIOR_MANAGER", "CEO")),
) -> list[TimeEntry]:
    entries = await get_time_entries_by_ids(db, approve_request.entry_ids, tenant_id=current_user.tenant_id)
    await _validate_weekly_batch(db, current_user, entries)

    try:
        approved_entries = await approve_time_entries_batch(
            db, approve_request.entry_ids, current_user.id, tenant_id=current_user.tenant_id)
        qb_service = get_quickbooks_service()
        for approved_entry in approved_entries:
            await qb_service.push_time_activity(approved_entry)

        # Audit: batch approve
        total_hours = sum(float(e.hours) for e in approved_entries)
        employee_id = entries[0].user_id if entries else None
        await record_activity_events(db, [build_activity_event(
            activity_type="TIME_ENTRIES_BATCH_APPROVED",
            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
            tenant_id=current_user.tenant_id,
            actor_user=current_user,
            entity_type="time_entry",
            summary=f"{current_user.full_name} approved {len(approved_entries)} time entries ({total_hours}h) for employee {employee_id}.",
            route="/approvals",
            metadata={"entry_ids": approve_request.entry_ids, "total_hours": total_hours, "employee_id": employee_id},
        )])

        return approved_entries
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/batch-reject", response_model=list[TimeEntryResponse])
async def reject_entry_batch(
    reject_request: TimeEntryBatchRejectRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role(
        "MANAGER", "SENIOR_MANAGER", "CEO")),
) -> list[TimeEntry]:
    entries = await get_time_entries_by_ids(db, reject_request.entry_ids, tenant_id=current_user.tenant_id)
    await _validate_weekly_batch(db, current_user, entries)

    try:
        rejected_entries = await reject_time_entries_batch(
            db,
            reject_request.entry_ids,
            current_user.id,
            reject_request.rejection_reason,
            tenant_id=current_user.tenant_id,
        )

        # Audit: batch reject
        total_hours = sum(float(e.hours) for e in rejected_entries)
        employee_id = entries[0].user_id if entries else None
        await record_activity_events(db, [build_activity_event(
            activity_type="TIME_ENTRIES_BATCH_REJECTED",
            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
            tenant_id=current_user.tenant_id,
            actor_user=current_user,
            entity_type="time_entry",
            summary=f"{current_user.full_name} rejected {len(rejected_entries)} time entries ({total_hours}h) for employee {employee_id}.",
            route="/approvals",
            metadata={"entry_ids": reject_request.entry_ids, "total_hours": total_hours, "employee_id": employee_id, "reason": reject_request.rejection_reason},
        )])

        return rejected_entries
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{entry_id}/approve", response_model=TimeEntryResponse)
async def approve_entry(
    entry_id: int,
    approve_request: TimeEntryApproveRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role(
        "MANAGER", "SENIOR_MANAGER", "CEO")),
) -> dict:
    """
    Approve a time entry (Manager/Senior Manager/CEO/Admin only).
    Pushes to QuickBooks service when approved.
    """
    entry = await get_time_entry_by_id(db, entry_id, tenant_id=current_user.tenant_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Time entry not found")

    if current_user.role.value != "CEO" and entry.user_id not in await _get_direct_report_ids(db, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only approve entries for your direct reports",
        )

    if entry.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot approve your own time entries",
        )

    try:
        approved_entry = await approve_time_entry(db, entry_id, current_user.id, tenant_id=current_user.tenant_id)

        # Push to QuickBooks (currently mock)
        qb_service = get_quickbooks_service()
        await qb_service.push_time_activity(approved_entry)

        # Audit: time entry approved
        await record_activity_events(db, [build_activity_event(
            activity_type="TIME_ENTRY_APPROVED",
            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
            tenant_id=current_user.tenant_id,
            actor_user=current_user,
            entity_type="time_entry",
            entity_id=entry_id,
            summary=f"{current_user.full_name} approved time entry #{entry_id} ({float(approved_entry.hours)}h) for employee {entry.user_id}.",
            route="/approvals",
            metadata={"hours": float(approved_entry.hours), "employee_id": entry.user_id, "entry_date": str(approved_entry.entry_date)},
        )])

        # Email notification to employee
        if entry.user and entry.user.email:
            await notify_timesheet_approved(
                employee_email=entry.user.email,
                employee_name=entry.user.full_name,
                approver_name=current_user.full_name,
                week_start=str(approved_entry.entry_date),
                week_end=str(approved_entry.entry_date),
                hours=float(approved_entry.hours),
                db=db,
            )

        return approved_entry
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{entry_id}/reject", response_model=TimeEntryResponse)
async def reject_entry(
    entry_id: int,
    reject_request: TimeEntryRejectRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role(
        "MANAGER", "SENIOR_MANAGER", "CEO")),
) -> dict:
    """
    Reject a time entry with a reason (Manager/Senior Manager/CEO/Admin only).
    """
    entry = await get_time_entry_by_id(db, entry_id, tenant_id=current_user.tenant_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Time entry not found")

    if current_user.role.value != "CEO" and entry.user_id not in await _get_direct_report_ids(db, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only reject entries for your direct reports",
        )

    if entry.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot reject your own time entries",
        )

    try:
        rejected_entry = await reject_time_entry(
            db, entry_id, current_user.id, reject_request.rejection_reason,
            tenant_id=current_user.tenant_id,
        )

        # Audit: time entry rejected
        await record_activity_events(db, [build_activity_event(
            activity_type="TIME_ENTRY_REJECTED",
            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
            tenant_id=current_user.tenant_id,
            actor_user=current_user,
            entity_type="time_entry",
            entity_id=entry_id,
            summary=f"{current_user.full_name} rejected time entry #{entry_id} for employee {entry.user_id}.",
            route="/approvals",
            metadata={"hours": float(rejected_entry.hours), "employee_id": entry.user_id, "reason": reject_request.rejection_reason},
        )])

        # Email notification to employee
        if entry.user and entry.user.email:
            await notify_timesheet_rejected(
                employee_email=entry.user.email,
                employee_name=entry.user.full_name,
                rejector_name=current_user.full_name,
                week_start=str(rejected_entry.entry_date),
                week_end=str(rejected_entry.entry_date),
                reason=reject_request.rejection_reason,
                db=db,
            )

        return rejected_entry
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{entry_id}/revert-rejection")
async def revert_entry_rejection(
    entry_id: int,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("MANAGER", "SENIOR_MANAGER", "CEO")),
) -> dict:
    """
    Revert a rejected time entry back to SUBMITTED so the manager
    can reconsider without asking the employee to resubmit.
    """
    entry = await db.get(TimeEntry, entry_id)
    if not entry or entry.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    if entry.status != TimeEntryStatus.REJECTED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only REJECTED entries can be reverted")

    entry.status = TimeEntryStatus.SUBMITTED
    entry.rejection_reason = None
    entry.updated_by = current_user.id
    await db.commit()
    return {"status": "submitted"}
