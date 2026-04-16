from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional
import time as time_module

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_role
from app.db import get_db
from app.models.assignments import EmployeeManagerAssignment
from app.models.activity_log import ActivityLog
from app.models.client import Client
from app.models.project import Project
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.time_off_request import TimeOffRequest, TimeOffStatus
from app.models.user import User, UserRole
from app.schemas import (
    DashboardActivity,
    DashboardAnalyticsResponse,
    DashboardBarEntryDetail,
    DashboardDayBreakdownDetailed,
    DashboardDayProjectSegment,
    DashboardProjectBreakdown,
    DashboardRecentActivityItem,
    DashboardSummaryResponse,
    TeamDailyOverviewResponse,
    UserResponse,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


async def _get_managed_employee_ids(db: AsyncSession, manager_id: int, as_of: Optional[date] = None) -> list[int]:
    query = select(EmployeeManagerAssignment.employee_id).where(
        EmployeeManagerAssignment.manager_id == manager_id
    )
    if as_of is not None:
        query = query.where(EmployeeManagerAssignment.created_at <=
                            datetime.combine(as_of, time.max))
    result = await db.execute(query)
    return list(result.scalars().all())


async def _get_managed_active_employee_ids(db: AsyncSession, manager_id: int, as_of: Optional[date] = None) -> list[int]:
    query = (
        select(User.id)
        .join(EmployeeManagerAssignment, EmployeeManagerAssignment.employee_id == User.id)
        .where(
            EmployeeManagerAssignment.manager_id == manager_id,
            User.role == UserRole.EMPLOYEE,
            User.is_active.is_(True),
        )
    )
    if as_of is not None:
        query = query.where(EmployeeManagerAssignment.created_at <=
                            datetime.combine(as_of, time.max))
    result = await db.execute(query)
    return list(result.scalars().all())


async def _get_direct_active_report_ids(db: AsyncSession, manager_id: int, as_of: Optional[date] = None) -> list[int]:
    query = (
        select(User.id)
        .join(EmployeeManagerAssignment, EmployeeManagerAssignment.employee_id == User.id)
        .where(
            EmployeeManagerAssignment.manager_id == manager_id,
            User.role == UserRole.EMPLOYEE,
            User.is_active.is_(True),
        )
    )
    if as_of is not None:
        query = query.where(EmployeeManagerAssignment.created_at <=
                            datetime.combine(as_of, time.max))
    result = await db.execute(query)
    return list(result.scalars().all())


async def _get_scoped_employee_ids(db: AsyncSession, current_user: "User") -> list[int]:
    """Return the list of active employee IDs that are in scope for the given user.

    - MANAGER: direct active employee reports only.
    - SENIOR_MANAGER: active employees under all direct manager/senior-manager
      reports, plus any employees directly assigned to the senior manager.
    - CEO / ADMIN: all active employees in the tenant.
    """
    if current_user.role == UserRole.MANAGER:
        return await _get_direct_active_report_ids(db, current_user.id)

    if current_user.role == UserRole.SENIOR_MANAGER:
        direct_report_ids = await _get_managed_employee_ids(db, current_user.id)
        employee_ids: list[int] = []
        for report_id in direct_report_ids:
            employee_ids.extend(await _get_direct_active_report_ids(db, report_id))
        # Also include employees directly assigned to the senior manager
        employee_ids.extend(await _get_direct_active_report_ids(db, current_user.id))
        return list(set(employee_ids))

    # CEO / ADMIN – whole tenant
    return await _get_all_active_employee_ids(db, tenant_id=current_user.tenant_id)


async def _get_all_active_employee_ids(db: AsyncSession, tenant_id: Optional[int] = None) -> list[int]:
    query = select(User.id).where(
        User.role == UserRole.EMPLOYEE,
        User.is_active.is_(True),
    )
    if tenant_id is not None:
        query = query.where(User.tenant_id == tenant_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def _get_all_active_user_ids(db: AsyncSession, tenant_id: int) -> list[int]:
    query = select(User.id).where(User.is_active.is_(True))
    query = query.where(User.tenant_id == tenant_id)
    result = await db.execute(query)
    return list(result.scalars().all())


def _week_start(value: date, week_start_day: int = 0) -> date:
    """0=Sunday, 1=Monday."""
    py_weekday = value.weekday()
    offset = (py_weekday + 1) % 7 if week_start_day == 0 else py_weekday
    return value - timedelta(days=offset)


async def _count_pending_timesheet_weeks(
    db: AsyncSession,
    tenant_id: int,
    user_ids: list[int] | None = None,
) -> int:
    from app.crud.time_entry import _tenant_week_start_day
    wsd = await _tenant_week_start_day(db, tenant_id)
    query = select(TimeEntry.user_id, TimeEntry.entry_date).where(
        TimeEntry.status == TimeEntryStatus.SUBMITTED
    )
    if user_ids is not None:
        if not user_ids:
            return 0
        query = query.where(TimeEntry.user_id.in_(user_ids))

    result = await db.execute(query)
    pending_weeks = {
        (user_id, _week_start(entry_date, wsd))
        for user_id, entry_date in result.all()
    }
    return len(pending_weeks)


def _previous_working_day(reference: date) -> date:
    candidate = reference - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _next_working_day(reference: date) -> date:
    candidate = reference + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    hours_logged_timesheet = await db.scalar(
        select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(
            (TimeEntry.user_id == current_user.id)
            & (TimeEntry.status.in_([TimeEntryStatus.DRAFT, TimeEntryStatus.SUBMITTED, TimeEntryStatus.APPROVED]))
        )
    )
    hours_logged_time_off = await db.scalar(
        select(func.coalesce(func.sum(TimeOffRequest.hours), 0)).where(
            (TimeOffRequest.user_id == current_user.id)
            & (TimeOffRequest.status.in_([TimeOffStatus.DRAFT, TimeOffStatus.SUBMITTED, TimeOffStatus.APPROVED]))
        )
    )

    approved_timesheet = await db.scalar(
        select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(
            (TimeEntry.user_id == current_user.id) & (
                TimeEntry.status == TimeEntryStatus.APPROVED)
        )
    )
    approved_time_off = await db.scalar(
        select(func.coalesce(func.sum(TimeOffRequest.hours), 0)).where(
            (TimeOffRequest.user_id == current_user.id) & (
                TimeOffRequest.status == TimeOffStatus.APPROVED)
        )
    )

    pending_timesheet = await db.scalar(
        select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(
            (TimeEntry.user_id == current_user.id) & (
                TimeEntry.status == TimeEntryStatus.SUBMITTED)
        )
    )
    pending_time_off = await db.scalar(
        select(func.coalesce(func.sum(TimeOffRequest.hours), 0)).where(
            (TimeOffRequest.user_id == current_user.id) & (
                TimeOffRequest.status == TimeOffStatus.SUBMITTED)
        )
    )

    pending_approvals = 0
    team_members = 0
    if current_user.role in [UserRole.MANAGER, UserRole.SENIOR_MANAGER, UserRole.CEO, UserRole.ADMIN]:
        scoped_employee_ids = await _get_scoped_employee_ids(db, current_user)

        pending_time_entries_count = await _count_pending_timesheet_weeks(
            db,
            current_user.tenant_id,
            scoped_employee_ids,
        )
        if scoped_employee_ids:
            pending_time_off_count = await db.scalar(
                select(func.count(TimeOffRequest.id)).where(
                    TimeOffRequest.status == TimeOffStatus.SUBMITTED,
                    TimeOffRequest.user_id.in_(scoped_employee_ids),
                )
            )
        else:
            pending_time_off_count = 0

        pending_approvals = int(
            pending_time_entries_count or 0) + int(pending_time_off_count or 0)
        team_members = len(scoped_employee_ids)

    return DashboardSummaryResponse(
        hours_logged=Decimal(str(hours_logged_timesheet or 0)) +
        Decimal(str(hours_logged_time_off or 0)),
        approved_hours=Decimal(str(approved_timesheet or 0)) +
        Decimal(str(approved_time_off or 0)),
        pending_hours=Decimal(str(pending_timesheet or 0)) +
        Decimal(str(pending_time_off or 0)),
        pending_approvals=pending_approvals,
        team_members=team_members,
    )


@router.get("/team", response_model=list[UserResponse])
async def get_dashboard_team(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.MANAGER, UserRole.SENIOR_MANAGER, UserRole.CEO, UserRole.ADMIN]:
        return []

    if current_user.role in [UserRole.MANAGER, UserRole.SENIOR_MANAGER]:
        managed_user_ids = await _get_scoped_employee_ids(db, current_user)
        if not managed_user_ids:
            return []
        query = select(User).where(User.id.in_(managed_user_ids)).where(User.is_active.is_(True))
    else:
        query = select(User).where(
            (User.role == UserRole.EMPLOYEE)
            & (User.is_active.is_(True))
            & (User.tenant_id == current_user.tenant_id)
        )

    result = await db.execute(
        query
        .options(
            selectinload(User.manager_assignment),
            selectinload(User.project_access),
        )
        .order_by(User.full_name.asc())
    )
    return result.scalars().all()


@router.get("/team-daily-overview", response_model=TeamDailyOverviewResponse)
async def get_team_daily_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now()
    target_date = _previous_working_day(now.date())
    deadline_day = _next_working_day(target_date)
    submission_deadline_at = datetime.combine(
        deadline_day, time(hour=10, minute=0))
    has_time_remaining_until_deadline = now < submission_deadline_at

    if current_user.role not in [UserRole.MANAGER, UserRole.SENIOR_MANAGER, UserRole.CEO, UserRole.ADMIN]:
        return TeamDailyOverviewResponse(
            date=target_date,
            submission_deadline_at=submission_deadline_at,
            has_time_remaining_until_deadline=has_time_remaining_until_deadline,
            team_size=0,
            submitted_yesterday_count=0,
            submitted_yesterday=[],
            draft_yesterday_count=0,
            draft_yesterday=[],
            missing_yesterday_count=0,
            missing_yesterday=[],
            pending_approvals_count=0,
            pending_time_entries_count=0,
            pending_time_off_count=0,
            total_hours_logged_yesterday=Decimal("0"),
        )

    team_member_ids = await _get_scoped_employee_ids(db, current_user)

    if not team_member_ids:
        return TeamDailyOverviewResponse(
            date=target_date,
            submission_deadline_at=submission_deadline_at,
            has_time_remaining_until_deadline=has_time_remaining_until_deadline,
            team_size=0,
            submitted_yesterday_count=0,
            submitted_yesterday=[],
            draft_yesterday_count=0,
            draft_yesterday=[],
            missing_yesterday_count=0,
            missing_yesterday=[],
            pending_approvals_count=0,
            pending_time_entries_count=0,
            pending_time_off_count=0,
            total_hours_logged_yesterday=Decimal("0"),
        )

    team_result = await db.execute(
        select(User)
        .where(User.id.in_(team_member_ids))
        .order_by(User.full_name.asc())
    )
    team_members = list(team_result.scalars().all())

    day_status_result = await db.execute(
        select(TimeEntry.user_id, TimeEntry.status)
        .where(
            TimeEntry.user_id.in_(team_member_ids),
            TimeEntry.entry_date == target_date,
        )
    )

    status_by_user: dict[int, set[TimeEntryStatus]] = {
        member.id: set() for member in team_members}
    for user_id, status in day_status_result.all():
        status_by_user.setdefault(user_id, set()).add(status)

    submitted_users: list[User] = []
    draft_users: list[User] = []
    missing_users: list[User] = []
    for member in team_members:
        statuses = status_by_user.get(member.id, set())
        if TimeEntryStatus.SUBMITTED in statuses or TimeEntryStatus.APPROVED in statuses:
            submitted_users.append(member)
        elif has_time_remaining_until_deadline:
            draft_users.append(member)
        else:
            missing_users.append(member)

    pending_time_entries_count = await _count_pending_timesheet_weeks(db, current_user.tenant_id, team_member_ids)
    pending_time_off_count = int(
        (await db.scalar(
            select(func.count(TimeOffRequest.id)).where(
                TimeOffRequest.user_id.in_(team_member_ids),
                TimeOffRequest.status == TimeOffStatus.SUBMITTED,
            )
        ))
        or 0
    )
    total_hours_logged_yesterday = Decimal(
        str(
            (await db.scalar(
                select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(
                    TimeEntry.user_id.in_(team_member_ids),
                    TimeEntry.entry_date == target_date,
                    TimeEntry.status.in_(
                        [TimeEntryStatus.SUBMITTED, TimeEntryStatus.APPROVED]),
                )
            ))
            or 0
        )
    )

    return TeamDailyOverviewResponse(
        date=target_date,
        submission_deadline_at=submission_deadline_at,
        has_time_remaining_until_deadline=has_time_remaining_until_deadline,
        team_size=len(team_members),
        submitted_yesterday_count=len(submitted_users),
        submitted_yesterday=submitted_users,
        draft_yesterday_count=len(draft_users),
        draft_yesterday=draft_users,
        missing_yesterday_count=len(missing_users),
        missing_yesterday=missing_users,
        pending_approvals_count=pending_time_entries_count + pending_time_off_count,
        pending_time_entries_count=pending_time_entries_count,
        pending_time_off_count=pending_time_off_count,
        total_hours_logged_yesterday=total_hours_logged_yesterday,
    )


@router.get("/analytics", response_model=DashboardAnalyticsResponse)
async def get_dashboard_analytics(
    start_date: date = Query(...),
    end_date: date = Query(...),
    project_id: Optional[int] = Query(None),
    user_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_user_ids = [current_user.id]
    if current_user.role in [UserRole.MANAGER, UserRole.SENIOR_MANAGER, UserRole.CEO, UserRole.ADMIN]:
        scoped_user_ids = await _get_scoped_employee_ids(db, current_user)

        if user_id is not None:
            if user_id in scoped_user_ids:
                target_user_ids = [user_id]
            elif user_id == current_user.id:
                target_user_ids = [current_user.id]
            else:
                target_user_ids = []
        else:
            target_user_ids = scoped_user_ids

    filters = [
        TimeEntry.user_id.in_(target_user_ids),
        TimeEntry.entry_date >= start_date,
        TimeEntry.entry_date <= end_date,
    ]
    if project_id is not None:
        filters.append(TimeEntry.project_id == project_id)

    total_hours = await db.scalar(
        select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(*filters)
    )

    billable_hours = await db.scalar(
        select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(
            *filters, TimeEntry.is_billable == True  # noqa: E712
        )
    )
    non_billable_hours = Decimal(
        str(total_hours or 0)) - Decimal(str(billable_hours or 0))

    daily_result = await db.execute(
        select(TimeEntry.entry_date, func.sum(TimeEntry.hours).label("hours"))
        .where(*filters)
        .group_by(TimeEntry.entry_date)
        .order_by(TimeEntry.entry_date.asc())
    )
    daily_map = {row.entry_date: Decimal(
        str(row.hours)) for row in daily_result.all()}

    daily_segment_result = await db.execute(
        select(
            TimeEntry.id,
            TimeEntry.entry_date,
            TimeEntry.hours,
            TimeEntry.status,
            TimeEntry.description,
            Project.id.label("project_id"),
            Project.name.label("project_name"),
            Client.name.label("client_name"),
        )
        .join(Project, TimeEntry.project_id == Project.id)
        .join(Client, Project.client_id == Client.id)
        .where(*filters)
        .order_by(TimeEntry.entry_date.asc(), Project.name.asc(), TimeEntry.id.asc())
    )

    segment_map: dict[date, dict[int, DashboardDayProjectSegment]] = {}
    for row in daily_segment_result.all():
        day_segments = segment_map.setdefault(row.entry_date, {})
        existing_segment = day_segments.get(row.project_id)
        if existing_segment is None:
            existing_segment = DashboardDayProjectSegment(
                project_id=row.project_id,
                project_name=row.project_name,
                client_name=row.client_name,
                hours=Decimal("0"),
                entries=[],
            )
            day_segments[row.project_id] = existing_segment

        entry_hours = Decimal(str(row.hours or 0))
        existing_segment.hours = Decimal(
            str(existing_segment.hours)) + entry_hours
        existing_segment.entries.append(
            DashboardBarEntryDetail(
                entry_id=row.id,
                project_id=row.project_id,
                project_name=row.project_name,
                client_name=row.client_name,
                status=row.status.value,
                description=row.description or "(no description)",
                hours=entry_hours,
                entry_date=row.entry_date,
            )
        )

    daily_breakdown: list[DashboardDayBreakdownDetailed] = []
    current_day = start_date
    while current_day <= end_date:
        day_segments = list(segment_map.get(current_day, {}).values())
        day_segments.sort(key=lambda segment: segment.project_name.lower())
        daily_breakdown.append(
            DashboardDayBreakdownDetailed(
                entry_date=current_day,
                hours=daily_map.get(current_day, Decimal("0")),
                formatted_date=current_day.strftime("%a, %b %d"),
                segments=day_segments,
            )
        )
        current_day += timedelta(days=1)

    project_result = await db.execute(
        select(
            Project.id,
            Project.name,
            Client.name.label("client_name"),
            func.sum(TimeEntry.hours).label("hours"),
        )
        .join(Project, TimeEntry.project_id == Project.id)
        .join(Client, Project.client_id == Client.id)
        .where(*filters)
        .group_by(Project.id, Project.name, Client.name)
        .order_by(func.sum(TimeEntry.hours).desc(), Project.name.asc())
    )
    project_rows = project_result.all()
    total_project_hours = sum((Decimal(str(row.hours))
                              for row in project_rows), Decimal("0"))

    project_breakdown: list[DashboardProjectBreakdown] = []
    for row in project_rows:
        hours = Decimal(str(row.hours))
        percentage = float((hours / total_project_hours) *
                           Decimal("100")) if total_project_hours > 0 else 0.0
        project_breakdown.append(
            DashboardProjectBreakdown(
                project_id=row.id,
                project_name=row.name,
                client_name=row.client_name,
                hours=hours,
                percentage=percentage,
            )
        )

    activity_result = await db.execute(
        select(
            TimeEntry.description,
            Project.name.label("project_name"),
            func.sum(TimeEntry.hours).label("hours"),
        )
        .join(Project, TimeEntry.project_id == Project.id)
        .where(*filters)
        .group_by(TimeEntry.description, Project.name)
        .order_by(func.sum(TimeEntry.hours).desc(), TimeEntry.description.asc())
        .limit(10)
    )
    top_activities = [
        DashboardActivity(
            description=row.description or "(no description)",
            project_name=row.project_name,
            hours=Decimal(str(row.hours)),
        )
        for row in activity_result.all()
    ]

    return DashboardAnalyticsResponse(
        total_hours=Decimal(str(total_hours or 0)),
        billable_hours=Decimal(str(billable_hours or 0)),
        non_billable_hours=non_billable_hours,
        top_project_name=project_breakdown[0].project_name if project_breakdown else None,
        top_client_name=project_breakdown[0].client_name if project_breakdown else None,
        daily_breakdown=daily_breakdown,
        project_breakdown=project_breakdown,
        top_activities=top_activities,
    )


@router.get("/recent-activity", response_model=list[DashboardRecentActivityItem])
async def get_recent_activity(
    limit: int = Query(8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DashboardRecentActivityItem]:
    if current_user.role == UserRole.PLATFORM_ADMIN:
        query = (
            select(ActivityLog)
            .where(ActivityLog.visibility_scope == "PLATFORM_ADMIN")
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .limit(limit)
        )
    elif current_user.role == UserRole.ADMIN and current_user.tenant_id is not None:
        query = (
            select(ActivityLog)
            .where(ActivityLog.visibility_scope == "TENANT_ADMIN")
            .where(ActivityLog.tenant_id == current_user.tenant_id)
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .limit(limit)
        )
    else:
        return []

    result = await db.execute(query)
    items = list(result.scalars().all())
    return [
        DashboardRecentActivityItem(
            id=item.id,
            activity_type=item.activity_type,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            actor_name=item.actor_name,
            summary=item.summary,
            route=item.route,
            route_params=item.route_params,
            metadata=item.metadata_json,
            severity=item.severity,
            created_at=item.created_at,
        )
        for item in items
    ]


@router.get("/audit-trail", response_model=list[DashboardRecentActivityItem])
async def get_audit_trail(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    activity_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> list[DashboardRecentActivityItem]:
    """Full audit trail for admins. Supports pagination, filtering by type, and text search."""
    if current_user.role == UserRole.PLATFORM_ADMIN:
        query = select(ActivityLog).where(ActivityLog.visibility_scope == "PLATFORM_ADMIN")
    else:
        query = (
            select(ActivityLog)
            .where(ActivityLog.visibility_scope == "TENANT_ADMIN")
            .where(ActivityLog.tenant_id == current_user.tenant_id)
        )

    if activity_type:
        query = query.where(ActivityLog.activity_type == activity_type)
    if search:
        query = query.where(ActivityLog.summary.ilike(f"%{search}%"))

    query = query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    items = list(result.scalars().all())
    return [
        DashboardRecentActivityItem(
            id=item.id,
            activity_type=item.activity_type,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            actor_name=item.actor_name,
            summary=item.summary,
            route=item.route,
            route_params=item.route_params,
            metadata=item.metadata_json,
            severity=item.severity,
            created_at=item.created_at,
        )
        for item in items
    ]
