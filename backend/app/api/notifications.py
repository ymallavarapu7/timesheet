from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db import get_db
from app.models.assignments import EmployeeManagerAssignment, UserProjectAccess
from app.models.notification import UserNotificationDismissal, UserNotificationState
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.time_off_request import TimeOffRequest, TimeOffStatus
from app.models.user import User, UserRole
from app.schemas import NotificationActionResponse, NotificationItem, NotificationReadRequest, NotificationRouteCounts, NotificationSummaryResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])
NOTIFICATION_TTL_DAYS = 7


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.replace(tzinfo=None)


def _add_notification(
    items: list[NotificationItem],
    *,
    notification_id: str,
    title: str,
    message: str,
    route: str,
    count: int,
    severity: str = "info",
    created_at: datetime | None = None,
) -> None:
    if count <= 0:
        return

    items.append(
        NotificationItem(
            id=notification_id,
            title=title,
            message=message,
            route=route,
            severity=severity,
            count=count,
            created_at=created_at,
        )
    )


def _previous_working_day(reference: date) -> date:
    previous = reference - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous


async def _get_managed_employee_ids(db: AsyncSession, manager_id: int) -> list[int]:
    result = await db.execute(
        select(EmployeeManagerAssignment.employee_id)
        .where(EmployeeManagerAssignment.manager_id == manager_id)
    )
    return list(result.scalars().all())


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


async def _get_pending_timesheet_week_stats(
    db: AsyncSession,
    employee_ids: list[int] | None = None,
) -> tuple[int, datetime | None]:
    query = select(TimeEntry.user_id, TimeEntry.entry_date, TimeEntry.submitted_at).where(
        TimeEntry.status == TimeEntryStatus.SUBMITTED
    )
    if employee_ids is not None:
        if not employee_ids:
            return 0, None
        query = query.where(TimeEntry.user_id.in_(employee_ids))

    result = await db.execute(query)
    rows = result.all()
    pending_weeks = {
        (user_id, _week_start(entry_date))
        for user_id, entry_date, _submitted_at in rows
    }
    latest_submitted_at = max(
        (_naive(submitted_at) for _user_id, _entry_date,
         submitted_at in rows if submitted_at is not None),
        default=None,
    )
    return len(pending_weeks), latest_submitted_at


@router.get("/summary", response_model=NotificationSummaryResponse)
async def get_notification_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import logging
    _logger = logging.getLogger(__name__)

    try:
        return await _build_notification_summary(db, current_user)
    except Exception as exc:
        _logger.exception("Notification summary failed for user %s: %s", current_user.id, exc)
        # Return empty summary instead of crashing
        return NotificationSummaryResponse(
            total_count=0,
            route_counts=NotificationRouteCounts(),
            items=[],
        )


async def _build_notification_summary(
    db: AsyncSession,
    current_user: User,
) -> NotificationSummaryResponse:
    items: list[NotificationItem] = []
    route_counts = NotificationRouteCounts()
    now = datetime.now(timezone.utc)
    current_time = now.time()
    ttl_cutoff = now - timedelta(days=NOTIFICATION_TTL_DAYS)
    ttl_cutoff_naive = ttl_cutoff.replace(tzinfo=None)  # For comparisons with _naive() results

    await db.execute(
        delete(UserNotificationState)
        .where(UserNotificationState.user_id == current_user.id)
        .where(UserNotificationState.last_read_at < ttl_cutoff)
    )
    await db.execute(
        delete(UserNotificationDismissal)
        .where(UserNotificationDismissal.user_id == current_user.id)
        .where(UserNotificationDismissal.deleted_at < ttl_cutoff)
    )

    year_start = date(now.year, 1, 1)
    today = now.date()
    rejected_time_entry_count, rejected_time_entry_latest = (
        await db.execute(
            select(func.count(TimeEntry.id), func.max(TimeEntry.updated_at)).where(
                (TimeEntry.user_id == current_user.id) & (
                    TimeEntry.status == TimeEntryStatus.REJECTED) & (
                    TimeEntry.entry_date >= year_start) & (
                    TimeEntry.entry_date <= today)
            )
        )
    ).one()
    _add_notification(
        items,
        notification_id="rejected-time-entries",
        title="Rejected time entries",
        message=f"{int(rejected_time_entry_count or 0)} time entr{'y' if int(rejected_time_entry_count or 0) == 1 else 'ies'} need correction and resubmission.",
        route="/my-time",
        count=int(rejected_time_entry_count or 0),
        severity="warning",
        created_at=rejected_time_entry_latest,
    )

    draft_time_entry_count, draft_time_entry_latest = (
        await db.execute(
            select(func.count(TimeEntry.id), func.max(TimeEntry.updated_at)).where(
                (TimeEntry.user_id == current_user.id) & (
                    TimeEntry.status == TimeEntryStatus.DRAFT) & (
                    TimeEntry.entry_date >= year_start) & (
                    TimeEntry.entry_date <= today)
            )
        )
    ).one()
    _add_notification(
        items,
        notification_id="draft-time-entries",
        title="Draft timesheet entries",
        message=f"{int(draft_time_entry_count or 0)} draft time entr{'y is' if int(draft_time_entry_count or 0) == 1 else 'ies are'} ready to review and submit.",
        route="/my-time",
        count=int(draft_time_entry_count or 0),
        severity="info",
        created_at=draft_time_entry_latest,
    )

    rejected_time_off_count, rejected_time_off_latest = (
        await db.execute(
            select(func.count(TimeOffRequest.id), func.max(TimeOffRequest.updated_at)).where(
                (TimeOffRequest.user_id == current_user.id) & (
                    TimeOffRequest.status == TimeOffStatus.REJECTED) & (
                    TimeOffRequest.request_date >= year_start) & (
                    TimeOffRequest.request_date <= today)
            )
        )
    ).one()
    _add_notification(
        items,
        notification_id="rejected-time-off",
        title="Rejected time off requests",
        message=f"{int(rejected_time_off_count or 0)} time off request{' needs' if int(rejected_time_off_count or 0) == 1 else 's need'} attention.",
        route="/time-off",
        count=int(rejected_time_off_count or 0),
        severity="warning",
        created_at=rejected_time_off_latest,
    )

    draft_time_off_count, draft_time_off_latest = (
        await db.execute(
            select(func.count(TimeOffRequest.id), func.max(TimeOffRequest.updated_at)).where(
                (TimeOffRequest.user_id == current_user.id) & (
                    TimeOffRequest.status == TimeOffStatus.DRAFT) & (
                    TimeOffRequest.request_date >= year_start) & (
                    TimeOffRequest.request_date <= today)
            )
        )
    ).one()
    _add_notification(
        items,
        notification_id="draft-time-off",
        title="Draft time off requests",
        message=f"{int(draft_time_off_count or 0)} draft time off request{' is' if int(draft_time_off_count or 0) == 1 else 's are'} ready to review and submit.",
        route="/time-off",
        count=int(draft_time_off_count or 0),
        severity="info",
        created_at=draft_time_off_latest,
    )

    week_start = date.today() - timedelta(days=date.today().weekday())
    previous_work_day = _previous_working_day(date.today())

    previous_day_entry_count = await db.scalar(
        select(func.count(TimeEntry.id)).where(
            (TimeEntry.user_id == current_user.id)
            & (TimeEntry.entry_date == previous_work_day)
        )
    )
    if current_time >= time(hour=8) and int(previous_day_entry_count or 0) == 0:
        reminder_anchor = datetime.combine(date.today(), time(hour=8))
        _add_notification(
            items,
            notification_id="missing-previous-day-entry",
            title="Missing yesterday's time entry",
            message=f"No time entry was logged for {previous_work_day.strftime('%b %d')}. Please add it today.",
            route="/my-time",
            count=1,
            severity="warning",
            created_at=reminder_anchor,
        )

    current_week_entry_count = await db.scalar(
        select(func.count(TimeEntry.id)).where(
            (TimeEntry.user_id == current_user.id)
            & (TimeEntry.entry_date >= week_start)
            & (TimeEntry.status.in_([TimeEntryStatus.DRAFT, TimeEntryStatus.SUBMITTED, TimeEntryStatus.APPROVED]))
        )
    )
    if int(current_week_entry_count or 0) == 0:
        week_anchor = datetime.combine(week_start, time.min)
        _add_notification(
            items,
            notification_id="weekly-timesheet-reminder",
            title="Weekly timesheet reminder",
            message="You have not logged any timesheet entries for this week yet.",
            route="/my-time",
            count=1,
            severity="info",
            created_at=week_anchor,
        )

    if current_user.role in [UserRole.MANAGER, UserRole.SENIOR_MANAGER]:
        assigned_employee_ids = await _get_managed_employee_ids(db, current_user.id)
        managed_employee_ids = assigned_employee_ids or None

        pending_time_off_query = select(func.count(TimeOffRequest.id), func.max(TimeOffRequest.submitted_at)).where(
            TimeOffRequest.status == TimeOffStatus.SUBMITTED
        )

        pending_time_entries_count, pending_time_entries_latest = await _get_pending_timesheet_week_stats(
            db,
            managed_employee_ids,
        )
        if managed_employee_ids is not None:
            pending_time_off_query = pending_time_off_query.where(
                TimeOffRequest.user_id.in_(managed_employee_ids))

        pending_time_off_count, pending_time_off_latest = (await db.execute(pending_time_off_query)).one()

        _add_notification(
            items,
            notification_id="pending-time-approvals",
            title="Pending time approvals",
            message=f"{int(pending_time_entries_count or 0)} submitted timesheet week{' requires' if int(pending_time_entries_count or 0) == 1 else 's require'} review.",
            route="/approvals",
            count=int(pending_time_entries_count or 0),
            severity="warning",
            created_at=pending_time_entries_latest,
        )
        _add_notification(
            items,
            notification_id="pending-timeoff-approvals",
            title="Pending time off approvals",
            message=f"{int(pending_time_off_count or 0)} time off request{' is' if int(pending_time_off_count or 0) == 1 else 's are'} waiting for review.",
            route="/approvals",
            count=int(pending_time_off_count or 0),
            severity="warning",
            created_at=pending_time_off_latest,
        )

        if current_time >= time(hour=14):
            employee_scope_ids: list[int] = []
            assigned_employee_ids = await _get_managed_employee_ids(db, current_user.id)
            employee_scope_ids = assigned_employee_ids

            missing_employee_count = 0
            if employee_scope_ids:
                entered_result = await db.execute(
                    select(TimeEntry.user_id)
                    .where(TimeEntry.user_id.in_(employee_scope_ids))
                    .where(TimeEntry.entry_date == previous_work_day)
                    .group_by(TimeEntry.user_id)
                )
                entered_ids = set(entered_result.scalars().all())
                missing_employee_count = len(
                    [employee_id for employee_id in employee_scope_ids if employee_id not in entered_ids]
                )

            escalation_anchor = datetime.combine(date.today(), time(hour=14))
            _add_notification(
                items,
                notification_id="missing-team-yesterday-entries",
                title="Missing team time entries",
                message=f"{missing_employee_count} employee{' has' if missing_employee_count == 1 else 's have'} not logged time for {previous_work_day.strftime('%b %d')}.",
                route="/approvals",
                count=missing_employee_count,
                severity="warning",
                created_at=escalation_anchor,
            )

    if current_user.role == UserRole.MANAGER:
        recent_assignment_count, recent_assignment_latest = (
            await db.execute(
                select(func.count(EmployeeManagerAssignment.employee_id),
                       func.max(EmployeeManagerAssignment.created_at))
                .where(
                    (EmployeeManagerAssignment.manager_id == current_user.id)
                    & (EmployeeManagerAssignment.created_at >= now - timedelta(days=7))
                )
            )
        ).one()
        _add_notification(
            items,
            notification_id="new-direct-reports",
            title="New employees assigned",
            message=f"{int(recent_assignment_count or 0)} employee{' has' if int(recent_assignment_count or 0) == 1 else 's have'} been assigned to you recently.",
            route="/dashboard",
            count=int(recent_assignment_count or 0),
            severity="info",
            created_at=recent_assignment_latest,
        )

    if current_user.role == UserRole.ADMIN:
        users_created_count, users_created_latest = (
            await db.execute(
                select(func.count(User.id), func.max(User.created_at)).where(
                    (User.id != current_user.id)
                    & (User.created_at >= now - timedelta(days=7))
                    & (User.tenant_id == current_user.tenant_id)
                )
            )
        ).one()
        _add_notification(
            items,
            notification_id="new-users-created",
            title="New users created",
            message=f"{int(users_created_count or 0)} new user account{' was' if int(users_created_count or 0) == 1 else 's were'} created in the last 7 days.",
            route="/admin",
            count=int(users_created_count or 0),
            severity="info",
            created_at=users_created_latest,
        )

        employees_without_manager_count, employees_without_manager_latest = (
            await db.execute(
                select(func.count(User.id), func.max(User.updated_at))
                .outerjoin(EmployeeManagerAssignment, EmployeeManagerAssignment.employee_id == User.id)
                .where(
                    (User.role == UserRole.EMPLOYEE)
                    & (User.is_active.is_(True))
                    & (User.tenant_id == current_user.tenant_id)
                    & (EmployeeManagerAssignment.employee_id.is_(None))
                )
            )
        ).one()
        _add_notification(
            items,
            notification_id="employees-without-manager",
            title="Employees without manager",
            message=f"{int(employees_without_manager_count or 0)} employee{' needs' if int(employees_without_manager_count or 0) == 1 else 's need'} a manager assignment.",
            route="/admin",
            count=int(employees_without_manager_count or 0),
            severity="warning",
            created_at=employees_without_manager_latest or now,
        )

        employees_without_projects_count, employees_without_projects_latest = (
            await db.execute(
                select(func.count(User.id), func.max(User.updated_at))
                .outerjoin(UserProjectAccess, UserProjectAccess.user_id == User.id)
                .where(
                    (User.role == UserRole.EMPLOYEE)
                    & (User.is_active.is_(True))
                    & (User.tenant_id == current_user.tenant_id)
                    & (UserProjectAccess.user_id.is_(None))
                )
            )
        ).one()
        _add_notification(
            items,
            notification_id="employees-without-projects",
            title="Employees without project access",
            message=f"{int(employees_without_projects_count or 0)} employee{' is' if int(employees_without_projects_count or 0) == 1 else 's are'} missing project access.",
            route="/admin",
            count=int(employees_without_projects_count or 0),
            severity="warning",
            created_at=employees_without_projects_latest or now,
        )

    items = [
        item for item in items
        if item.created_at is None or _naive(item.created_at) >= ttl_cutoff_naive
    ]

    if items:
        notification_ids = [item.id for item in items]
        read_state_result = await db.execute(
            select(UserNotificationState)
            .where(UserNotificationState.user_id == current_user.id)
            .where(
                UserNotificationState.notification_id.in_(
                    notification_ids + ["*"])
            )
        )
        read_state_map = {
            state.notification_id: _naive(state.last_read_at)
            for state in read_state_result.scalars().all()
        }
        dismissed_state_result = await db.execute(
            select(UserNotificationDismissal)
            .where(UserNotificationDismissal.user_id == current_user.id)
            .where(
                UserNotificationDismissal.notification_id.in_(
                    notification_ids + ["*"])
            )
        )
        dismissed_state_map = {
            state.notification_id: _naive(state.deleted_at)
            for state in dismissed_state_result.scalars().all()
        }
        global_last_read_at = read_state_map.get("*")
        global_deleted_at = dismissed_state_map.get("*")

        unread_route_counts = NotificationRouteCounts()
        visible_items: list[NotificationItem] = []
        for item in items:
            item_created_at = _naive(item.created_at)
            is_deleted = False
            if item_created_at is not None:
                deleted_at = dismissed_state_map.get(item.id)
                if deleted_at is not None and item_created_at <= deleted_at:
                    is_deleted = True
                if global_deleted_at is not None and item_created_at <= global_deleted_at:
                    is_deleted = True

            if is_deleted:
                continue

            is_read = False
            if item_created_at is not None:
                last_read_at = read_state_map.get(item.id)
                if last_read_at is not None and item_created_at <= last_read_at:
                    is_read = True
                if global_last_read_at is not None and item_created_at <= global_last_read_at:
                    is_read = True

            item.is_read = is_read
            visible_items.append(item)
            if not is_read:
                if item.route == "/my-time":
                    unread_route_counts.my_time += item.count
                elif item.route == "/time-off":
                    unread_route_counts.time_off += item.count
                elif item.route == "/approvals":
                    unread_route_counts.approvals += item.count
                elif item.route == "/admin":
                    unread_route_counts.admin += item.count
                else:
                    unread_route_counts.dashboard += item.count

        items = visible_items
        route_counts = unread_route_counts

    items.sort(key=lambda item: _naive(item.created_at)
               or datetime.min, reverse=True)
    await db.commit()

    total_count = (
        route_counts.my_time
        + route_counts.time_off
        + route_counts.approvals
        + route_counts.admin
        + route_counts.dashboard
    )

    return NotificationSummaryResponse(
        total_count=total_count,
        route_counts=route_counts,
        items=items,
    )


@router.post("/read", response_model=NotificationActionResponse)
async def mark_notification_read(
    payload: NotificationReadRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing_result = await db.execute(
        select(UserNotificationState)
        .where(UserNotificationState.user_id == current_user.id)
        .where(UserNotificationState.notification_id == payload.notification_id)
    )
    existing = existing_result.scalars().first()

    if existing is None:
        db.add(
            UserNotificationState(
                user_id=current_user.id,
                notification_id=payload.notification_id,
                last_read_at=datetime.now(timezone.utc),
            )
        )
    else:
        existing.last_read_at = datetime.now(timezone.utc)
        db.add(existing)

    await db.commit()
    return NotificationActionResponse(success=True)


@router.post("/delete", response_model=NotificationActionResponse)
async def delete_notification(
    payload: NotificationReadRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing_result = await db.execute(
        select(UserNotificationDismissal)
        .where(UserNotificationDismissal.user_id == current_user.id)
        .where(UserNotificationDismissal.notification_id == payload.notification_id)
    )
    existing = existing_result.scalars().first()

    if existing is None:
        db.add(
            UserNotificationDismissal(
                user_id=current_user.id,
                notification_id=payload.notification_id,
                deleted_at=datetime.now(timezone.utc),
            )
        )
    else:
        existing.deleted_at = datetime.now(timezone.utc)
        db.add(existing)

    await db.commit()
    return NotificationActionResponse(success=True)


@router.post("/read-all", response_model=NotificationActionResponse)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(
        delete(UserNotificationState).where(
            UserNotificationState.user_id == current_user.id)
    )

    # Store wildcard read anchor so current notifications become read at once.
    db.add(
        UserNotificationState(
            user_id=current_user.id,
            notification_id="*",
            last_read_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return NotificationActionResponse(success=True)


@router.post("/delete-all", response_model=NotificationActionResponse)
async def delete_all_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(
        delete(UserNotificationDismissal).where(
            UserNotificationDismissal.user_id == current_user.id)
    )

    db.add(
        UserNotificationDismissal(
            user_id=current_user.id,
            notification_id="*",
            deleted_at=datetime.now(timezone.utc),
        )
    )

    await db.commit()
    return NotificationActionResponse(success=True)
