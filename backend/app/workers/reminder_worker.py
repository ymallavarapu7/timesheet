"""
Reminder worker — runs every 15 minutes via arq.
Checks all tenants with reminders enabled and sends
emails to employees/contractors who are behind on submissions.
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.email_sender_mapping import EmailSenderMapping
from app.models.ingested_email import IngestedEmail
from app.services.email_service import send_email

logger = logging.getLogger(__name__)

DAY_NAME_TO_WEEKDAY = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}


async def check_and_send_reminders(ctx: dict) -> None:
    """arq task — check all tenants and send due reminders."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.status == "active")
        )
        tenants = result.scalars().all()

        for tenant in tenants:
            try:
                await _process_tenant_reminders(tenant.id, session)
            except Exception as exc:
                logger.error(
                    "Reminder check failed for tenant %s: %s",
                    tenant.id, exc
                )


async def _process_tenant_reminders(tenant_id: int, session) -> None:
    tenant_settings = await _load_tenant_settings(tenant_id, session)
    now = datetime.now(timezone.utc)

    if tenant_settings.get("reminder_internal_enabled") == "true":
        await _check_internal_reminders(tenant_id, tenant_settings, now, session)

    if tenant_settings.get("reminder_external_enabled") == "true":
        await _check_external_reminders(tenant_id, tenant_settings, now, session)


async def _check_internal_reminders(
    tenant_id: int, tenant_settings: dict, now: datetime, session
) -> None:
    """
    Send reminder to employees who have not submitted for the current week.
    Triggered at: (deadline_time - 3h) and at (deadline_time).
    If locking is enabled and deadline has passed, lock the user.
    """
    deadline_day = tenant_settings.get("reminder_internal_deadline_day", "friday").lower()
    deadline_time_str = tenant_settings.get("reminder_internal_deadline_time", "17:00")
    lock_enabled = tenant_settings.get("reminder_internal_lock_enabled") == "true"

    weekday = DAY_NAME_TO_WEEKDAY.get(deadline_day, 4)  # default friday

    try:
        dh, dm = map(int, deadline_time_str.split(":"))
    except (ValueError, AttributeError):
        dh, dm = 17, 0

    # Find the most recent occurrence of deadline_day
    days_since = (now.weekday() - weekday) % 7
    deadline_date = now.date() - timedelta(days=days_since)
    deadline_dt = datetime(
        deadline_date.year, deadline_date.month, deadline_date.day,
        dh, dm, tzinfo=timezone.utc
    )

    # Trigger windows: at (deadline - 3h) and at deadline (within 15-min window)
    window_start_early = deadline_dt - timedelta(hours=3)
    window_start_final = deadline_dt
    in_early_window = window_start_early <= now < window_start_early + timedelta(minutes=15)
    in_final_window = window_start_final <= now < window_start_final + timedelta(minutes=15)
    deadline_passed = now >= deadline_dt

    if not (in_early_window or in_final_window or (lock_enabled and deadline_passed)):
        return

    # Determine recipient list
    recipients_setting = tenant_settings.get("reminder_internal_recipients", "all")
    if recipients_setting == "all":
        user_result = await session.execute(
            select(User).where(
                (User.tenant_id == tenant_id) &
                (User.role == UserRole.EMPLOYEE) &
                (User.is_active == True)  # noqa: E712
            )
        )
        employees = user_result.scalars().all()
    else:
        try:
            user_ids = [int(x.strip()) for x in recipients_setting.split(",") if x.strip()]
        except ValueError:
            return
        user_result = await session.execute(
            select(User).where(
                (User.tenant_id == tenant_id) &
                (User.id.in_(user_ids)) &
                (User.is_active == True)  # noqa: E712
            )
        )
        employees = user_result.scalars().all()

    # Current week start (Monday)
    week_start = now.date() - timedelta(days=now.weekday())

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

            if lock_enabled and deadline_passed and not employee.timesheet_locked:
                employee.timesheet_locked = True
                employee.timesheet_locked_reason = f"Missed submission deadline ({deadline_day} {deadline_time_str})"
                logger.info("Locked timesheet for %s (tenant %s)", employee.email, tenant_id)

    await session.commit()


async def _check_external_reminders(
    tenant_id: int, tenant_settings: dict, now: datetime, session
) -> None:
    """
    Send reminder to contractors who have not submitted a timesheet this month.
    Triggered at: (deadline - 2 days) and (deadline - 3h).
    """
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

    deadline_dt = datetime(now.year, now.month, target_day, dh, dm, tzinfo=timezone.utc)
    window_2day = deadline_dt - timedelta(days=2)
    window_3h = deadline_dt - timedelta(hours=3)

    in_2day_window = window_2day <= now < window_2day + timedelta(minutes=15)
    in_3h_window = window_3h <= now < window_3h + timedelta(minutes=15)

    if not (in_2day_window or in_3h_window):
        return

    # Load all active sender mappings for this tenant
    mapping_result = await session.execute(
        select(EmailSenderMapping).where(
            EmailSenderMapping.tenant_id == tenant_id
        )
    )
    mappings = mapping_result.scalars().all()

    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    for mapping in mappings:
        if not mapping.sender_email:
            continue
        # Check if any email arrived from this sender this month
        email_result = await session.execute(
            select(IngestedEmail.id).where(
                (IngestedEmail.tenant_id == tenant_id) &
                (IngestedEmail.sender_email == mapping.sender_email) &
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
            await send_email(to_address=mapping.sender_email, subject=subject, body_text=body)
            logger.info("Sent contractor reminder to %s (tenant %s)", mapping.sender_email, tenant_id)


async def _load_tenant_settings(tenant_id: int, session) -> dict:
    from app.models.tenant_settings import TenantSettings
    result = await session.execute(
        select(TenantSettings).where(
            TenantSettings.tenant_id == tenant_id
        )
    )
    rows = result.scalars().all()
    return {row.key: row.value for row in rows}
