import csv
import io
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.models.assignments import EmployeeManagerAssignment
from app.schemas import (
    TimeEntryResponse, TimeEntryCreate, TimeEntryUpdate,
    TimeEntryWithUser, TimeEntrySubmitRequest, WeeklySubmissionStatusResponse
)
from app.crud.time_entry import (
    get_time_entry_by_id, create_time_entry, update_time_entry, delete_time_entry,
    get_weekly_submission_status, list_user_entries, list_tenant_entries, submit_time_entries
)
from app.crud.project import user_has_project_access, get_project_by_id
from app.crud.task import get_task_by_id
from app.core.deps import get_current_user
from app.models.user import User, UserRole
from app.models.time_entry import TimeEntryStatus
from datetime import date
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/timesheets", tags=["timesheets"])


# ── Natural Language Parsing ────────────────────────────────────────

class NaturalLanguageRequest(BaseModel):
    text: str


@router.post("/parse-natural")
async def parse_natural_language(
    body: NaturalLanguageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Parse a natural language sentence into structured time entry data.
    Returns parsed entries with project/task/hours/date resolved from
    the user's assigned projects. Does NOT create entries — the frontend
    uses the result to populate the form for user review.
    """
    from app.services.nl_time_entry import parse_natural_language_entry

    result = await parse_natural_language_entry(db, current_user, body.text)
    return result


@router.get("/my", response_model=list[TimeEntryWithUser])
async def get_my_timesheets(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    status: Optional[TimeEntryStatus] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query(
        "entry_date", pattern="^(entry_date|created_at|hours|status)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list:
    """
    Get current user's time entries with optional filters.
    """
    return await list_user_entries(
        db,
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        status=status,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )


@router.get("/weekly-submit-status", response_model=WeeklySubmissionStatusResponse)
async def get_weekly_submit_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    can_submit, reason, due_date = await get_weekly_submission_status(db, current_user.id)
    return WeeklySubmissionStatusResponse(
        can_submit=can_submit,
        reason=reason,
        due_date=due_date,
    )


@router.get("/all", response_model=list[TimeEntryWithUser])
async def get_all_timesheets(
    user_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    status: Optional[TimeEntryStatus] = Query(None),
    sort_by: str = Query("entry_date", pattern="^(entry_date|created_at|hours|status)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list:
    """
    Get time entries for the entire tenant (Admin/CEO/Senior Manager/Manager only).
    Optionally filter by a specific employee via user_id.
    """
    allowed = {UserRole.ADMIN, UserRole.PLATFORM_ADMIN, UserRole.CEO, UserRole.SENIOR_MANAGER, UserRole.MANAGER}
    if current_user.role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Managers and Senior Managers only see their reporting tree's entries
    effective_user_id = user_id
    scoped_user_ids: list[int] | None = None
    if current_user.role in (UserRole.MANAGER, UserRole.SENIOR_MANAGER) and not user_id:
        # Get full descendant tree
        descendant_ids: set[int] = set()
        frontier: set[int] = {current_user.id}
        while frontier:
            result = await db.execute(
                sa_select(EmployeeManagerAssignment.employee_id)
                .where(EmployeeManagerAssignment.manager_id.in_(frontier))
            )
            children = set(result.scalars().all())
            next_frontier = children - descendant_ids
            descendant_ids.update(next_frontier)
            frontier = next_frontier
        scoped_user_ids = list(descendant_ids) if descendant_ids else []

    if scoped_user_ids is not None and not scoped_user_ids:
        return []

    # If scoped, fetch entries for each managed user
    if scoped_user_ids is not None:
        all_entries = []
        for uid in scoped_user_ids:
            entries = await list_user_entries(
                db, user_id=uid, start_date=start_date, end_date=end_date,
                status=status, sort_by=sort_by, sort_order=sort_order,
                skip=0, limit=limit,
            )
            all_entries.extend(entries)
        return all_entries[:limit]

    return await list_tenant_entries(
        db,
        tenant_id=current_user.tenant_id,
        user_id=effective_user_id,
        start_date=start_date,
        end_date=end_date,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )


@router.get("/export")
async def export_time_entries(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    status_filter: Optional[TimeEntryStatus] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export time entries as CSV. Admins/Managers get all tenant entries; employees get their own."""
    from app.models.time_entry import TimeEntry
    from app.models.project import Project
    from sqlalchemy.orm import selectinload

    query = (
        sa_select(TimeEntry)
        .options(
            selectinload(TimeEntry.user),
            selectinload(TimeEntry.project).selectinload(Project.client),
            selectinload(TimeEntry.task),
        )
    )

    if current_user.role in (UserRole.ADMIN, UserRole.PLATFORM_ADMIN):
        if current_user.tenant_id:
            query = query.where(TimeEntry.tenant_id == current_user.tenant_id)
    elif current_user.role in (UserRole.MANAGER, UserRole.SENIOR_MANAGER, UserRole.CEO):
        if current_user.tenant_id:
            query = query.where(TimeEntry.tenant_id == current_user.tenant_id)
    else:
        query = query.where(TimeEntry.user_id == current_user.id)

    if start_date:
        query = query.where(TimeEntry.entry_date >= start_date)
    if end_date:
        query = query.where(TimeEntry.entry_date <= end_date)
    if status_filter:
        query = query.where(TimeEntry.status == status_filter)

    query = query.order_by(TimeEntry.entry_date.asc(), TimeEntry.user_id)
    result = await db.execute(query)
    entries = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Employee", "Email", "Client", "Project", "Task",
        "Date", "Day", "Hours", "Billable", "Status", "Description",
    ])
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for entry in entries:
        writer.writerow([
            entry.user.full_name if entry.user else "",
            entry.user.email if entry.user else "",
            entry.project.client.name if entry.project and entry.project.client else "",
            entry.project.name if entry.project else "",
            entry.task.name if entry.task else "",
            str(entry.entry_date),
            day_names[entry.entry_date.weekday()] if entry.entry_date else "",
            float(entry.hours),
            "Yes" if entry.is_billable else "No",
            entry.status.value if hasattr(entry.status, 'value') else str(entry.status),
            entry.description or "",
        ])

    output.seek(0)
    filename = f"timesheet_export_{start_date or 'all'}_{end_date or 'all'}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{entry_id}", response_model=TimeEntryWithUser)
async def get_timesheet_entry(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Get a specific time entry.
    Users can only view their own entries unless they are admin/manager.
    """
    entry = await get_time_entry_by_id(db, entry_id, tenant_id=current_user.tenant_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Time entry not found")

    # Check access
    if entry.user_id != current_user.id and current_user.role.value == "EMPLOYEE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return entry


@router.post("", response_model=TimeEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_timesheet_entry(
    entry_create: TimeEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Create a new time entry for the current user.
    Employees can only create entries for themselves.
    """
    # Employees, managers, and system admins can create their own time entries
    if current_user.role.value not in ["EMPLOYEE", "MANAGER", "ADMIN"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only employees, managers, and system admins can create time entries")

    if not await user_has_project_access(db, current_user, entry_create.project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to the selected project",
        )

    project = await get_project_by_id(db, entry_create.project_id, tenant_id=current_user.tenant_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected project not found",
        )
    if not project.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected project is inactive",
        )

    if entry_create.task_id is not None:
        task = await get_task_by_id(db, entry_create.task_id, tenant_id=current_user.tenant_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected task not found",
            )
        if not task.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected task is inactive",
            )
        if task.project_id != entry_create.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected task does not belong to selected project",
            )

    try:
        new_entry = await create_time_entry(db, current_user.id, current_user.tenant_id, entry_create)
        return new_entry
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.put("/{entry_id}", response_model=TimeEntryResponse)
async def update_timesheet_entry(
    entry_id: int,
    entry_update: TimeEntryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Update a time entry (only DRAFT entries can be updated).
    Users can only edit their own DRAFT entries.
    """
    entry = await get_time_entry_by_id(db, entry_id, tenant_id=current_user.tenant_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Time entry not found")

    # Check access
    if entry.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Can only edit your own entries")

    # Check status — allow editing DRAFT and REJECTED entries
    if entry.status not in (TimeEntryStatus.DRAFT, TimeEntryStatus.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only edit DRAFT or REJECTED entries"
        )

    if entry_update.project_id is not None and not await user_has_project_access(db, current_user, entry_update.project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to the selected project",
        )

    if entry_update.project_id is not None:
        project = await get_project_by_id(db, entry_update.project_id, tenant_id=current_user.tenant_id)
        if not project or not project.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected project is inactive",
            )

    if entry_update.task_id is not None:
        effective_project_id = entry_update.project_id or entry.project_id
        task = await get_task_by_id(db, entry_update.task_id, tenant_id=current_user.tenant_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected task not found",
            )
        if not task.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected task is inactive",
            )
        if task.project_id != effective_project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected task does not belong to selected project",
            )

    try:
        updated_entry = await update_time_entry(
            db, entry, entry_update, edited_by=current_user.id)
        return updated_entry
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_timesheet_entry(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete a time entry (only DRAFT entries can be deleted).
    Users can only delete their own DRAFT entries.
    """
    entry = await get_time_entry_by_id(db, entry_id, tenant_id=current_user.tenant_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Time entry not found")

    # Check access
    if entry.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Can only delete your own entries")

    success = await delete_time_entry(db, entry_id, tenant_id=current_user.tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only delete DRAFT entries"
        )


@router.post("/submit", response_model=list[TimeEntryResponse])
async def submit_timesheets(
    submit_request: TimeEntrySubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list:
    """
    Submit time entries for approval.
    Employees submit their own entries; managers can submit for their team.
    """
    try:
        submitted_entries = await submit_time_entries(db, current_user.id, submit_request.entry_ids)
        return submitted_entries
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


