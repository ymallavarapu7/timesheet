"""
Reminder worker — runs every 15 minutes via arq.
Checks all tenants with reminders enabled and sends
emails to employees/contractors who are behind on submissions.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy import select
from app.core.timezone_utils import now_for_tenant
from app.db import AsyncSessionLocal
from app.models.assignments import EmployeeManagerAssignment
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.ingested_email import IngestedEmail
from app.services.email_service import send_email

logger = logging.getLogger(__name__)

DAY_NAME_TO_WEEKDAY = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}


async def _eligible_internal_reminder_recipients(
    session,
    tenant_id: int,
    *,
    user_ids: list[int] | None = None,
    max_created_at: datetime | None = None,
) -> list[User]:
    """EMPLOYEE users who can submit a timesheet (active, verified, unlocked,
    has a manager, not external). ``max_created_at`` excludes brand-new
    accounts from the auto-lock path."""
    conditions = [
        User.tenant_id == tenant_id,
        User.role == UserRole.EMPLOYEE,
        User.is_active.is_(True),
        User.email_verified.is_(True),
        User.timesheet_locked.is_(False),
        User.is_external.is_(False),
    ]
    if user_ids is not None:
        conditions.append(User.id.in_(user_ids))
    if max_created_at is not None:
        conditions.append(User.created_at < max_created_at)

    stmt = (
        select(User)
        .join(
            EmployeeManagerAssignment,
            EmployeeManagerAssignment.employee_id == User.id,
        )
        .where(*conditions)
        .distinct()
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def check_and_send_reminders(ctx: dict) -> None:
    """arq task: fan out over active tenants and send due reminders."""
    from app.db_control import AsyncControlSessionLocal
    from app.db_tenant import tenant_session
    from app.models.control import ControlTenant

    async with AsyncControlSessionLocal() as control_session:
        result = await control_session.execute(
            select(ControlTenant).where(ControlTenant.status == "active")
        )
        control_tenants = list(result.scalars().all())

    for control_tenant in control_tenants:
        try:
            async with tenant_session(control_tenant.slug) as session:
                # Re-hydrate the per-tenant Tenant row for tenant.timezone.
                tenant_row = await session.get(Tenant, control_tenant.id)
                if tenant_row is None:
                    logger.warning(
                        "Skipping reminders for control tenant %s (%s): "
                        "no matching row in tenant DB",
                        control_tenant.id, control_tenant.slug,
                    )
                    continue
                await _process_tenant_reminders(tenant_row, session)
        except Exception as exc:
            logger.error(
                "Reminder check failed for tenant %s (%s): %s",
                control_tenant.id, control_tenant.slug, exc,
            )


async def _process_tenant_reminders(tenant: Tenant, session) -> None:
    tenant_id = tenant.id
    tenant_timezone = tenant.timezone
    tenant_settings = await _load_tenant_settings(tenant_id, session)
    now = now_for_tenant(tenant_timezone)

    if tenant_settings.get("reminder_internal_enabled") == "true":
        await _check_internal_reminders(
            tenant_id, tenant_settings, tenant_timezone, now, session
        )

    if tenant_settings.get("reminder_external_enabled") == "true":
        await _check_external_reminders(
            tenant_id, tenant_settings, tenant_timezone, now, session
        )


async def _check_internal_reminders(
    tenant_id: int,
    tenant_settings: dict,
    tenant_timezone: Optional[str],
    now: datetime,
    session,
) -> None:
    """
    Send reminder to employees who have not submitted for the current week.
    Triggered at: (deadline_time - 3h) and at (deadline_time).
    If locking is enabled and deadline has passed, lock the user.

    ``tenant_timezone`` is accepted for parity with the external path and to
    document the contract — ``now`` is already tz-aware, so downstream math
    uses ``now.tzinfo`` directly.
    """
    del tenant_timezone  # already encoded in ``now.tzinfo``
    deadline_day = tenant_settings.get("reminder_internal_deadline_day", "friday").lower()
    deadline_time_str = tenant_settings.get("reminder_internal_deadline_time", "17:00")
    lock_enabled = tenant_settings.get("reminder_internal_lock_enabled") == "true"

    weekday = DAY_NAME_TO_WEEKDAY.get(deadline_day, 4)  # default friday

    try:
        dh, dm = map(int, deadline_time_str.split(":"))
    except (ValueError, AttributeError):
        dh, dm = 17, 0

    # Find the most recent occurrence of deadline_day. ``now`` is already in
    # the tenant's timezone; compute the deadline in the same tz so the
    # wall-clock comparison (``Friday 17:00``) fires at the right moment for
    # tenants in non-UTC zones.
    tz = now.tzinfo or timezone.utc
    days_since = (now.weekday() - weekday) % 7
    deadline_date = now.date() - timedelta(days=days_since)
    deadline_dt = datetime(
        deadline_date.year, deadline_date.month, deadline_date.day,
        dh, dm, tzinfo=tz
    )

    # Trigger windows: at (deadline - 3h) and at deadline (within 15-min window)
    window_start_early = deadline_dt - timedelta(hours=3)
    window_start_final = deadline_dt
    in_early_window = window_start_early <= now < window_start_early + timedelta(minutes=15)
    in_final_window = window_start_final <= now < window_start_final + timedelta(minutes=15)
    deadline_passed = now >= deadline_dt

    if not (in_early_window or in_final_window or (lock_enabled and deadline_passed)):
        return

    # Current week start (Monday) in the tenant's timezone.
    week_start = now.date() - timedelta(days=now.weekday())
    week_start_dt = datetime(
        week_start.year, week_start.month, week_start.day, tzinfo=tz
    )

    # Determine recipient list. The auto-lock branch uses a stricter filter
    # (accounts must predate week_start) so it's applied only when we're about
    # to lock, not when we're sending reminders.
    recipients_setting = tenant_settings.get("reminder_internal_recipients", "all")
    restricted_user_ids: list[int] | None = None
    if recipients_setting != "all":
        try:
            restricted_user_ids = [
                int(x.strip()) for x in recipients_setting.split(",") if x.strip()
            ]
        except ValueError:
            return

    employees = await _eligible_internal_reminder_recipients(
        session, tenant_id, user_ids=restricted_user_ids
    )
    logger.info(
        "internal_reminder: %d recipients for tenant %s",
        len(employees), tenant_id,
    )

    # Auto-lock uses the same eligibility plus an account-age guard.
    lock_candidates: list[User] = []
    if lock_enabled and deadline_passed:
        lock_candidates = await _eligible_internal_reminder_recipients(
            session,
            tenant_id,
            user_ids=restricted_user_ids,
            max_created_at=week_start_dt,
        )
        logger.info(
            "auto_lock: locking %d users in tenant %s for missed deadline %s",
            len(lock_candidates), tenant_id, deadline_dt.isoformat(),
        )
    lock_candidate_ids = {u.id for u in lock_candidates}

    for employee in employees:
        # Check if they have any SUBMITTED entries this week
        submitted_result = await session.execute(
            select(TimeEntry.id).where(
                (TimeEntry.user_id == employee.id) &
                (TimeEntry.tenant_id == tenant_id) &
                (TimeEntry.status == TimeEntryStatus.SUBMITTED) &
                (TimeEntry.entry_date >= week_start)
            ).limit(1)
        )
        has_submitted = submitted_result.scalar_one_or_none() is not None

        if not has_submitted:
            if in_early_window or in_final_window:
                subject = "Reminder: Timesheet submission due soon"
                body = (
                    f"Dear {employee.full_name},\n\n"
                    f"This is a reminder that your timesheet is due by "
                    f"{deadline_day.capitalize()} at {deadline_time_str}.\n\n"
                    f"Please submit your timesheet before the deadline.\n\n"
                    f"Regards,\nAcufy Platform"
                )
                await send_email(to_address=employee.email, subject=subject, body_text=body)
                logger.info("Sent reminder to %s (tenant %s)", employee.email, tenant_id)

            if (
                lock_enabled
                and deadline_passed
                and not employee.timesheet_locked
                and employee.id in lock_candidate_ids
            ):
                employee.timesheet_locked = True
                employee.timesheet_locked_reason = f"Missed submission deadline ({deadline_day} {deadline_time_str})"
                logger.info("Locked timesheet for %s (tenant %s)", employee.email, tenant_id)

    await session.commit()


async def _check_external_reminders(
    tenant_id: int,
    tenant_settings: dict,
    tenant_timezone: Optional[str],
    now: datetime,
    session,
) -> None:
    """
    Send reminder to contractors who have not submitted a timesheet this month.
    Triggered at: (deadline - 2 days) and (deadline - 3h).

    ``tenant_timezone`` is accepted for parity with the internal path and to
    document the contract — ``now`` is already tz-aware, so downstream math
    uses ``now.tzinfo`` directly.
    """
    del tenant_timezone  # already encoded in ``now.tzinfo``
    day_of_month_str = tenant_settings.get("reminder_external_deadline_day_of_month", "-2")
    deadline_time_str = tenant_settings.get("reminder_external_deadline_time", "17:00")

    try:
        day_offset = int(day_of_month_str)
        dh, dm = map(int, deadline_time_str.split(":"))
    except (ValueError, AttributeError):
        return

    import calendar
    last_day = calendar.monthrange(now.year, now.month)[1]
    if day_offset < 0:
        target_day = last_day + day_offset + 1
    else:
        target_day = day_offset
    target_day = max(1, min(target_day, last_day))

    # Build deadline in the tenant's timezone so the wall-clock match fires
    # at the correct moment for non-UTC tenants.
    tz = now.tzinfo or timezone.utc
    deadline_dt = datetime(now.year, now.month, target_day, dh, dm, tzinfo=tz)
    window_2day = deadline_dt - timedelta(days=2)
    window_3h = deadline_dt - timedelta(hours=3)

    in_2day_window = window_2day <= now < window_2day + timedelta(minutes=15)
    in_3h_window = window_3h <= now < window_3h + timedelta(minutes=15)

    if not (in_2day_window or in_3h_window):
        return

    # External contractors are modeled as users with is_external=True. Remind
    # anyone whose email hasn't produced an ingested email this calendar month.
    # Require email_verified so we don't remind invitees who haven't accepted
    # yet — consistent with the internal-reminder eligibility helper.
    external_result = await session.execute(
        select(User).where(
            (User.tenant_id == tenant_id)
            & (User.is_external == True)  # noqa: E712
            & (User.is_active == True)  # noqa: E712
            & (User.email_verified == True)  # noqa: E712
        )
    )
    externals = external_result.scalars().all()
    logger.info(
        "external_reminder: %d recipients for tenant %s",
        len(externals), tenant_id,
    )

    month_start = datetime(now.year, now.month, 1, tzinfo=tz)

    for external in externals:
        if not external.email or external.email.endswith("@ingestion.internal"):
            continue
        # Check if any email arrived from this sender this month
        email_result = await session.execute(
            select(IngestedEmail.id).where(
                (IngestedEmail.tenant_id == tenant_id) &
                (IngestedEmail.sender_email == external.email) &
                (IngestedEmail.received_at >= month_start)
            ).limit(1)
        )
        has_submitted = email_result.scalar_one_or_none() is not None

        if not has_submitted:
            subject = "Reminder: Monthly timesheet submission due soon"
            body = (
                f"Dear Contractor,\n\n"
                f"This is a reminder that your monthly timesheet submission is due by "
                f"the {target_day}{'st' if target_day == 1 else 'th'} of this month at {deadline_time_str}.\n\n"
                f"Please submit your timesheet before the deadline.\n\n"
                f"Regards,\nAcufy Platform"
            )
            await send_email(to_address=external.email, subject=subject, body_text=body)
            logger.info("Sent contractor reminder to %s (tenant %s)", external.email, tenant_id)


async def _load_tenant_settings(tenant_id: int, session) -> dict:
    from app.models.tenant_settings import TenantSettings
    result = await session.execute(
        select(TenantSettings).where(
            TenantSettings.tenant_id == tenant_id
        )
    )
    rows = result.scalars().all()
    return {row.key: row.value for row in rows}
