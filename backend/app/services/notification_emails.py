"""
Email notifications for key timesheet events.
All functions are fire-and-forget — failures are logged, never raised.
"""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.email_service import send_email

logger = logging.getLogger(__name__)


async def notify_timesheet_approved(
    employee_email: str,
    employee_name: str,
    approver_name: str,
    week_start: str,
    week_end: str,
    hours: float,
    db: Optional[AsyncSession] = None,
) -> None:
    subject = f"Timesheet approved — {week_start} to {week_end}"
    body_text = (
        f"Hi {employee_name},\n\n"
        f"Your timesheet for {week_start} to {week_end} ({hours} hours) has been approved by {approver_name}.\n\n"
        f"— Acufy AI"
    )
    body_html = (
        f"<p>Hi {employee_name},</p>"
        f"<p>Your timesheet for <strong>{week_start} to {week_end}</strong> ({hours} hours) "
        f"has been approved by {approver_name}.</p>"
        f"<p>— Acufy AI</p>"
    )
    try:
        await send_email(employee_email, subject, body_text, body_html, db=db)
    except Exception as exc:
        logger.warning("Failed to send approval notification to %s: %s", employee_email, exc)


async def notify_timesheet_rejected(
    employee_email: str,
    employee_name: str,
    rejector_name: str,
    week_start: str,
    week_end: str,
    reason: str,
    db: Optional[AsyncSession] = None,
) -> None:
    subject = f"Timesheet rejected — {week_start} to {week_end}"
    body_text = (
        f"Hi {employee_name},\n\n"
        f"Your timesheet for {week_start} to {week_end} has been rejected by {rejector_name}.\n\n"
        f"Reason: {reason}\n\n"
        f"Please review and resubmit.\n\n"
        f"— Acufy AI"
    )
    body_html = (
        f"<p>Hi {employee_name},</p>"
        f"<p>Your timesheet for <strong>{week_start} to {week_end}</strong> "
        f"has been rejected by {rejector_name}.</p>"
        f"<p><strong>Reason:</strong> {reason}</p>"
        f"<p>Please review and resubmit.</p>"
        f"<p>— Acufy AI</p>"
    )
    try:
        await send_email(employee_email, subject, body_text, body_html, db=db)
    except Exception as exc:
        logger.warning("Failed to send rejection notification to %s: %s", employee_email, exc)


async def notify_time_off_approved(
    employee_email: str,
    employee_name: str,
    approver_name: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    db: Optional[AsyncSession] = None,
) -> None:
    subject = f"Time off approved — {leave_type}"
    body_text = (
        f"Hi {employee_name},\n\n"
        f"Your {leave_type} request for {start_date} to {end_date} has been approved by {approver_name}.\n\n"
        f"— Acufy AI"
    )
    body_html = (
        f"<p>Hi {employee_name},</p>"
        f"<p>Your <strong>{leave_type}</strong> request for {start_date} to {end_date} "
        f"has been approved by {approver_name}.</p>"
        f"<p>— Acufy AI</p>"
    )
    try:
        await send_email(employee_email, subject, body_text, body_html, db=db)
    except Exception as exc:
        logger.warning("Failed to send time off approval notification to %s: %s", employee_email, exc)


async def notify_time_off_rejected(
    employee_email: str,
    employee_name: str,
    rejector_name: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    reason: str,
    db: Optional[AsyncSession] = None,
) -> None:
    subject = f"Time off rejected — {leave_type}"
    body_text = (
        f"Hi {employee_name},\n\n"
        f"Your {leave_type} request for {start_date} to {end_date} has been rejected by {rejector_name}.\n\n"
        f"Reason: {reason}\n\n"
        f"— Acufy AI"
    )
    body_html = (
        f"<p>Hi {employee_name},</p>"
        f"<p>Your <strong>{leave_type}</strong> request for {start_date} to {end_date} "
        f"has been rejected by {rejector_name}.</p>"
        f"<p><strong>Reason:</strong> {reason}</p>"
        f"<p>— Acufy AI</p>"
    )
    try:
        await send_email(employee_email, subject, body_text, body_html, db=db)
    except Exception as exc:
        logger.warning("Failed to send time off rejection notification to %s: %s", employee_email, exc)
