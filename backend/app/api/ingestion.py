import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import require_can_review, require_ingestion_enabled
from app.crud.ingestion_timesheet import (
    get_ingestion_timesheet,
    list_ingestion_timesheets,
    write_audit_log,
)
from app.db import get_db
from app.models.client import Client
from app.models.email_attachment import EmailAttachment
from app.models.email_sender_mapping import EmailSenderMapping, SenderMatchType
from app.models.ingested_email import IngestedEmail
from app.models.ingestion_timesheet import (
    IngestionAuditLog,
    IngestionTimesheet,
    IngestionTimesheetLineItem,
    IngestionTimesheetStatus,
)
from app.models.project import Project
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.user import User
from app.schemas.ingestion import (
    CleanupSkippedNoiseResponse,
    ApprovalResult,
    ApproveRequest,
    DraftCommentRequest,
    DraftCommentResponse,
    FetchJobResponse,
    FetchJobStatus,
    HoldRequest,
    IngestionTimesheetDetail,
    IngestionTimesheetSummary,
    LineItemCreate,
    LineItemRead,
    LineItemUpdate,
    MappingReapplyResult,
    ReprocessStoredEmailRequest,
    ReprocessStoredEmailResponse,
    ReprocessSkippedResponse,
    SkippedEmailOverview,
    RejectRequest,
    StoredEmailDetail,
    TimesheetDataUpdate,
)
from app.services.llm_ingestion import draft_comment
from app.services.storage import delete_file, read_file
from app.workers.email_fetch import enqueue_fetch_job, get_job_status

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _timesheet_to_summary(timesheet: IngestionTimesheet, rejected_sender_set: set[str] | None = None) -> dict:
    email = timesheet.email
    push_status = "Sent" if timesheet.time_entries_created else "Not sent"
    is_likely_resubmission = False
    if rejected_sender_set and timesheet.email:
        sender = timesheet.email.sender_email or ""
        is_likely_resubmission = (
            bool(sender) and
            sender in rejected_sender_set and
            _enum_value(timesheet.status) == "pending"
        )
    return {
        "id": timesheet.id,
        "tenant_id": timesheet.tenant_id,
        "email_id": timesheet.email_id,
        "attachment_id": timesheet.attachment_id,
        "subject": email.subject if email else None,
        "sender_email": email.sender_email if email else None,
        "sender_name": email.sender_name if email else None,
        "employee_id": timesheet.employee_id,
        "employee_name": timesheet.employee.full_name if timesheet.employee else None,
        "extracted_employee_name": (timesheet.extracted_data or {}).get("employee_name"),
        "client_id": timesheet.client_id,
        "client_name": timesheet.client.name if timesheet.client else None,
        "period_start": timesheet.period_start,
        "period_end": timesheet.period_end,
        "total_hours": timesheet.total_hours,
        "status": _enum_value(timesheet.status),
        "push_status": push_status,
        "time_entries_created": timesheet.time_entries_created,
        "llm_anomalies": timesheet.llm_anomalies,
        "received_at": email.received_at if email else None,
        "submitted_at": timesheet.submitted_at,
        "reviewed_at": timesheet.reviewed_at,
        "created_at": timesheet.created_at,
        "is_likely_resubmission": is_likely_resubmission,
    }


def _normalize_match_value(match_type: SenderMatchType, value: str) -> str:
    value = value.strip().lower()
    if match_type == SenderMatchType.domain and "@" in value:
        return value.split("@", 1)[1]
    return value


def _infer_skipped_email_reason(
    email: IngestedEmail,
    attachments: list[EmailAttachment],
) -> tuple[str | None, str | None]:
    llm_classification = email.llm_classification or {}
    skip_reason = llm_classification.get("pipeline_skip_reason")
    skip_detail = llm_classification.get("pipeline_skip_detail")
    if skip_reason:
        return skip_reason, skip_detail

    if not attachments:
        return "no_attachments", "The email was ingested without any attachments."

    candidate_attachments = [attachment for attachment in attachments if attachment.is_timesheet]
    if not candidate_attachments:
        return (
            "no_candidate_timesheet_attachment",
            "Attachments were present, but none matched the current timesheet detection rules.",
        )

    if all(attachment.extraction_status == "failed" for attachment in candidate_attachments):
        return (
            "attachment_extraction_failed",
            "Candidate timesheet attachments were found, but all of them failed during extraction.",
        )

    if all(attachment.extraction_status == "completed" for attachment in candidate_attachments):
        return (
            "no_structured_timesheet_data",
            "Attachment extraction completed, but no staged timesheet rows were created.",
        )

    return None, None


def _is_actionable_skipped_email(
    email: IngestedEmail,
    attachments: list[EmailAttachment],
    skip_reason: str | None,
) -> bool:
    def _has_timesheet_keywords(value: str | None) -> bool:
        if not value:
            return False
        text = value.lower()
        keywords = (
            "timesheet",
            "time sheet",
            "timecard",
            "time card",
            "hours worked",
            "billable",
            "work log",
            "weekly hours",
        )
        return any(keyword in text for keyword in keywords)

    llm_classification = email.llm_classification or {}
    intent = str(llm_classification.get("intent") or "").lower()
    is_timesheet_email = bool(llm_classification.get("is_timesheet_email"))
    submission_intents = {
        "new_submission",
        "resubmission",
        "correction",
        "submission",
        "timesheet_submission",
    }

    has_timesheet_filename_hint = any(
        _has_timesheet_keywords(attachment.filename)
        for attachment in attachments
    )
    has_timesheet_context = (
        is_timesheet_email
        or intent in submission_intents
        or _has_timesheet_keywords(email.subject)
        or has_timesheet_filename_hint
    )

    if skip_reason and (
        skip_reason.startswith("not_timesheet_email:")
        or skip_reason.startswith("low_confidence_no_attachments:")
    ):
        return False

    # If extraction failed but there are no timesheet signals, treat as noise
    # (e.g., invoices/receipts that happen to be processable documents).
    if skip_reason == "attachment_extraction_failed" and not has_timesheet_context:
        return False

    if skip_reason == "no_structured_timesheet_data" and not has_timesheet_context:
        return False

    # Keep candidate attachments only when timesheet context is present.
    if any(attachment.is_timesheet for attachment in attachments):
        return has_timesheet_context

    # Non-timesheet items without candidate attachments are noise for reviewers.
    if not email.has_attachments:
        return False

    return False


def _timesheet_to_detail(timesheet: IngestionTimesheet) -> dict:
    email = timesheet.email
    attachments: list[dict] = []
    if email:
        for attachment in email.attachments or []:
            attachments.append(
                {
                    "id": attachment.id,
                    "filename": attachment.filename,
                    "mime_type": attachment.mime_type,
                    "size_bytes": attachment.size_bytes,
                    "is_timesheet": attachment.is_timesheet,
                    "extraction_method": _enum_value(attachment.extraction_method) if attachment.extraction_method else None,
                    "extraction_status": _enum_value(attachment.extraction_status),
                    "extraction_error": attachment.extraction_error,
                    "raw_extracted_text": attachment.raw_extracted_text,
                }
            )

    return {
        "id": timesheet.id,
        "tenant_id": timesheet.tenant_id,
        "attachment_id": timesheet.attachment_id,
        "status": _enum_value(timesheet.status),
        "employee_id": timesheet.employee_id,
        "employee_name": timesheet.employee.full_name if timesheet.employee else None,
        "client_id": timesheet.client_id,
        "client_name": timesheet.client.name if timesheet.client else None,
        "reviewer_id": timesheet.reviewer_id,
        "period_start": timesheet.period_start,
        "period_end": timesheet.period_end,
        "total_hours": timesheet.total_hours,
        "extracted_data": timesheet.extracted_data,
        "corrected_data": timesheet.corrected_data,
        "llm_anomalies": timesheet.llm_anomalies,
        "llm_match_suggestions": timesheet.llm_match_suggestions,
        "llm_summary": timesheet.llm_summary,
        "rejection_reason": timesheet.rejection_reason,
        "internal_notes": timesheet.internal_notes,
        "submitted_at": timesheet.submitted_at,
        "reviewed_at": timesheet.reviewed_at,
        "created_at": timesheet.created_at,
        "updated_at": timesheet.updated_at,
        "time_entries_created": timesheet.time_entries_created,
        "extracted_employee_name": (timesheet.extracted_data or {}).get("employee_name"),
        "email": {
            "id": email.id,
            "subject": email.subject,
            "sender_email": email.sender_email,
            "sender_name": email.sender_name,
            "recipients": email.recipients,
            "body_text": email.body_text,
            "body_html": email.body_html,
            "received_at": email.received_at,
            "attachments": attachments,
        } if email else None,
        "line_items": [
            {
                "id": item.id,
                "work_date": item.work_date,
                "hours": item.hours,
                "description": item.description,
                "project_code": item.project_code,
                "project_id": item.project_id,
                "is_corrected": item.is_corrected,
                "original_value": item.original_value,
                "is_rejected": getattr(item, "is_rejected", False),
                "rejection_reason": getattr(item, "rejection_reason", None),
            }
            for item in (timesheet.line_items or [])
        ],
        "audit_log": [
            {
                "id": log.id,
                "action": log.action,
                "actor_type": _enum_value(log.actor_type),
                "user_id": log.user_id,
                "previous_value": log.previous_value,
                "new_value": log.new_value,
                "comment": log.comment,
                "created_at": log.created_at,
            }
            for log in (timesheet.audit_log or [])
        ],
    }


def _attachment_to_read_dict(attachment: EmailAttachment) -> dict:
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "mime_type": attachment.mime_type,
        "size_bytes": attachment.size_bytes,
        "is_timesheet": attachment.is_timesheet,
        "extraction_method": _enum_value(attachment.extraction_method) if attachment.extraction_method else None,
        "extraction_status": _enum_value(attachment.extraction_status),
        "extraction_error": attachment.extraction_error,
        "raw_extracted_text": attachment.raw_extracted_text,
    }


def _stored_email_to_detail(email: IngestedEmail, attachments: list[EmailAttachment]) -> dict:
    llm_classification = email.llm_classification or {}
    skip_reason, skip_detail = _infer_skipped_email_reason(email, attachments)
    return {
        "id": email.id,
        "subject": email.subject,
        "sender_email": email.sender_email,
        "sender_name": email.sender_name,
        "recipients": email.recipients,
        "body_text": email.body_text,
        "body_html": email.body_html,
        "received_at": email.received_at,
        "mailbox_label": email.mailbox.label if email.mailbox else None,
        "classification_intent": llm_classification.get("intent"),
        "skip_reason": skip_reason,
        "skip_detail": skip_detail,
        "llm_classification": llm_classification,
        "attachments": [_attachment_to_read_dict(attachment) for attachment in attachments],
    }


async def _load_ingested_email_for_delete(
    session: AsyncSession,
    email_id: int,
    tenant_id: int,
) -> IngestedEmail | None:
    result = await session.execute(
        select(IngestedEmail)
        .where(
            (IngestedEmail.id == email_id)
            & (IngestedEmail.tenant_id == tenant_id)
        )
        .options(
            selectinload(IngestedEmail.mailbox),
            selectinload(IngestedEmail.attachments),
            selectinload(IngestedEmail.ingestion_timesheets).selectinload(IngestionTimesheet.line_items),
            selectinload(IngestedEmail.ingestion_timesheets).selectinload(IngestionTimesheet.audit_log),
        )
    )
    return result.scalar_one_or_none()


async def _delete_ingested_email_tree(
    session: AsyncSession,
    email_record: IngestedEmail,
) -> list[str]:
    attachments = list(email_record.attachments or [])
    storage_keys = [attachment.storage_key for attachment in attachments]
    timesheets = list(email_record.ingestion_timesheets or [])

    for timesheet in timesheets:
        for audit in list(timesheet.audit_log or []):
            await session.delete(audit)
        for line_item in list(timesheet.line_items or []):
            await session.delete(line_item)
        await session.delete(timesheet)

    for attachment in attachments:
        await session.delete(attachment)

    await session.delete(email_record)
    return storage_keys


async def _validate_employee(
    session: AsyncSession,
    current_user: User,
    employee_id: int | None,
) -> None:
    if employee_id is None:
        return

    employee = await session.get(User, employee_id)
    if not employee:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Employee not found")
    if employee.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: employee belongs to a different tenant",
        )


async def _validate_client(
    session: AsyncSession,
    current_user: User,
    client_id: int | None,
) -> None:
    if client_id is None:
        return

    client = await session.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Client not found")
    if client.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: client belongs to a different tenant",
        )


async def _validate_project(
    session: AsyncSession,
    current_user: User,
    project_id: int | None,
) -> Project | None:
    if project_id is None:
        return None

    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project not found")
    if project.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: project belongs to a different tenant",
        )
    return project


async def _resolve_project_for_line_item(
    session: AsyncSession,
    current_user: User,
    item: IngestionTimesheetLineItem,
) -> int | None:
    if item.project_id is not None:
        project = await _validate_project(session, current_user, item.project_id)
        if project and not project.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Project {project.id} is inactive for line item {item.id}",
            )
        return item.project_id

    if item.project_code:
        result = await session.execute(
            select(Project).where(
                (Project.tenant_id == current_user.tenant_id) &
                (Project.code == item.project_code) &
                (Project.is_active == True)
            )
        )
        project = result.scalar_one_or_none()
        if project:
            return project.id

    # Non-blocking path: reviewer can approve even when project mapping is incomplete.
    return None


@router.post("/fetch-emails", response_model=FetchJobResponse)
async def trigger_fetch_emails(
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
) -> dict:
    try:
        job_id = await enqueue_fetch_job(current_user.tenant_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Fetch job queued for this tenant.",
    }


@router.get("/fetch-emails/status/{job_id}", response_model=FetchJobStatus)
async def fetch_email_status(
    job_id: str,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
) -> dict:
    try:
        payload = await get_job_status(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    tenant_id = payload.get("tenant_id")
    if tenant_id is not None and tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if tenant_id is None:
        expected_prefix = f"fetch_tenant_{current_user.tenant_id}"
        tenant_token = f"_tenant_{current_user.tenant_id}_"
        if job_id != expected_prefix and tenant_token not in job_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return payload


@router.get("/skipped-emails", response_model=SkippedEmailOverview)
async def list_skipped_emails(
    limit: int = Query(10, ge=1, le=50),
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    result = await session.execute(
        select(IngestedEmail)
        .where(
            (IngestedEmail.tenant_id == current_user.tenant_id)
            & (~IngestedEmail.ingestion_timesheets.any())
        )
        .options(selectinload(IngestedEmail.mailbox))
        .order_by(IngestedEmail.received_at.desc().nullslast(), IngestedEmail.id.desc())
    )
    skipped_emails = list(result.scalars().all())

    summary_rows: list[dict] = []
    for email in skipped_emails[:limit]:
        attachment_result = await session.execute(
            select(EmailAttachment).where(EmailAttachment.email_id == email.id)
        )
        attachments = list(attachment_result.scalars().all())
        llm_classification = email.llm_classification or {}
        skip_reason, skip_detail = _infer_skipped_email_reason(email, attachments)
        if not _is_actionable_skipped_email(email, attachments, skip_reason):
            continue
        summary_rows.append(
            {
                "id": email.id,
                "subject": email.subject,
                "sender_email": email.sender_email,
                "sender_name": email.sender_name,
                "received_at": email.received_at,
                "mailbox_label": email.mailbox.label if email.mailbox else None,
                "has_attachments": email.has_attachments,
                "timesheet_attachment_count": sum(1 for attachment in attachments if attachment.is_timesheet),
                "classification_intent": llm_classification.get("intent"),
                "skip_reason": skip_reason,
                "skip_detail": skip_detail,
                "reprocessable_attachments": [
                    {
                        "id": attachment.id,
                        "filename": attachment.filename,
                        "mime_type": attachment.mime_type,
                        "extraction_status": _enum_value(attachment.extraction_status),
                    }
                    for attachment in attachments
                    if attachment.is_timesheet
                ],
            }
        )

    return {
        "count": len(summary_rows),
        "emails": summary_rows,
    }


@router.post("/skipped-emails/cleanup-noise", response_model=CleanupSkippedNoiseResponse)
async def cleanup_skipped_email_noise(
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    result = await session.execute(
        select(IngestedEmail)
        .where(
            (IngestedEmail.tenant_id == current_user.tenant_id)
            & (~IngestedEmail.ingestion_timesheets.any())
        )
        .options(selectinload(IngestedEmail.attachments))
        .order_by(IngestedEmail.id.desc())
    )
    skipped_emails = list(result.scalars().all())

    deleted_emails = 0
    deleted_attachments = 0
    deleted_files = 0
    file_delete_errors = 0
    storage_keys_to_delete: list[str] = []

    for email in skipped_emails:
        attachments = list(email.attachments or [])
        skip_reason, _ = _infer_skipped_email_reason(email, attachments)
        if _is_actionable_skipped_email(email, attachments, skip_reason):
            continue

        deleted_attachments += len(attachments)
        storage_keys = await _delete_ingested_email_tree(session, email)
        storage_keys_to_delete.extend(storage_keys)
        deleted_emails += 1

    await session.commit()

    for storage_key in storage_keys_to_delete:
        try:
            await delete_file(storage_key)
            deleted_files += 1
        except FileNotFoundError:
            continue
        except Exception:
            file_delete_errors += 1

    return {
        "scanned_emails": len(skipped_emails),
        "deleted_emails": deleted_emails,
        "deleted_attachments": deleted_attachments,
        "deleted_files": deleted_files,
        "file_delete_errors": file_delete_errors,
    }


@router.post("/fetch-emails/reprocess-skipped", response_model=ReprocessSkippedResponse)
async def reprocess_skipped_emails(
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    try:
        job_id = await enqueue_fetch_job(current_user.tenant_id, mode="reprocess_skipped")
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return {
        "job_id": job_id,
        "status": "queued",
        "deleted_emails": 0,
        "deleted_attachments": 0,
        "deleted_files": 0,
        "file_delete_errors": 0,
    }


@router.post("/fetch-emails/reprocess", response_model=ReprocessStoredEmailResponse)
async def reprocess_stored_email_route(
    body: ReprocessStoredEmailRequest,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    email_result = await session.execute(
        select(IngestedEmail).where(
            (IngestedEmail.id == body.email_id)
            & (IngestedEmail.tenant_id == current_user.tenant_id)
        )
    )
    email_record = email_result.scalar_one_or_none()
    if email_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")

    if body.attachment_ids:
        attachment_result = await session.execute(
            select(EmailAttachment).where(
                (EmailAttachment.email_id == body.email_id)
                & (EmailAttachment.id.in_(body.attachment_ids))
            )
        )
        matched_ids = {attachment.id for attachment in attachment_result.scalars().all()}
        if matched_ids != set(body.attachment_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more attachments do not belong to this email.",
            )

    mode = "reprocess_attachments" if body.attachment_ids else "reprocess_email"
    try:
        job_id = await enqueue_fetch_job(
            current_user.tenant_id,
            mode=mode,
            email_id=body.email_id,
            attachment_ids=body.attachment_ids or [],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": mode,
        "email_id": body.email_id,
    }


@router.get("/emails/{email_id}", response_model=StoredEmailDetail)
async def get_stored_email(
    email_id: int,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    email_record = await _load_ingested_email_for_delete(session, email_id, current_user.tenant_id)
    if email_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")

    attachments = list(email_record.attachments or [])
    return _stored_email_to_detail(email_record, attachments)


@router.post("/emails/{email_id}/reprocess", status_code=status.HTTP_200_OK)
async def reprocess_single_email(
    email_id: int,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    from app.models.mailbox import Mailbox
    from app.services.imap import fetch_single_message
    from app.services.ingestion_pipeline import process_email

    email_record = await _load_ingested_email_for_delete(session, email_id, current_user.tenant_id)
    if email_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")

    mailbox_result = await session.execute(
        select(Mailbox).where(Mailbox.id == email_record.mailbox_id)
    )
    mailbox = mailbox_result.scalar_one_or_none()
    if mailbox is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailbox for this email not found")

    try:
        raw_message = await fetch_single_message(
            mailbox=mailbox,
            message_id=email_record.message_id,
            session=session,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not re-fetch email from mailbox: {exc}",
        ) from exc

    if not raw_message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email no longer found in mailbox",
        )

    storage_keys = await _delete_ingested_email_tree(session, email_record)
    await session.flush()

    pipeline_result = await process_email(
        raw_message=raw_message,
        mailbox_id=mailbox.id,
        tenant_id=current_user.tenant_id,
        session=session,
    )

    if pipeline_result.email_id is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Reprocessing failed before a replacement email record could be created.",
        )

    for storage_key in storage_keys:
        try:
            await delete_file(storage_key)
        except FileNotFoundError:
            continue

    return {
        "status": "reprocessed",
        "email_id": email_id,
        "new_email_id": pipeline_result.email_id,
        "timesheets_created": pipeline_result.timesheets_created,
        "skipped": pipeline_result.skipped,
        "skip_reason": pipeline_result.skip_reason,
        "errors": pipeline_result.errors,
    }


@router.delete("/emails/{email_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ingested_email(
    email_id: int,
    refetch: bool = Query(False, description="Reset mailbox cursor so the next Fetch Emails will re-ingest this email"),
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> None:
    email_record = await _load_ingested_email_for_delete(session, email_id, current_user.tenant_id)
    if email_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")

    # If refetch requested, reset the mailbox cursor so the next fetch includes this email
    if refetch and email_record.received_at and email_record.mailbox_id:
        from app.models.mailbox import Mailbox
        mailbox_result = await session.execute(
            select(Mailbox).where(Mailbox.id == email_record.mailbox_id)
        )
        mailbox = mailbox_result.scalar_one_or_none()
        if mailbox:
            # Set cursor to just before the deleted email's received_at
            from datetime import timedelta
            new_cursor = email_record.received_at - timedelta(minutes=10)
            if mailbox.last_fetched_at is None or new_cursor < mailbox.last_fetched_at:
                mailbox.last_fetched_at = new_cursor

    storage_keys = await _delete_ingested_email_tree(session, email_record)
    await session.commit()

    for storage_key in storage_keys:
        try:
            await delete_file(storage_key)
        except FileNotFoundError:
            continue


class BulkDeleteEmailsRequest(BaseModel):
    email_ids: list[int]


@router.post("/emails/bulk-delete")
async def bulk_delete_ingested_emails(
    body: BulkDeleteEmailsRequest,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    deleted = 0
    all_storage_keys: list[str] = []
    for email_id in body.email_ids:
        email_record = await _load_ingested_email_for_delete(session, email_id, current_user.tenant_id)
        if email_record is None:
            continue
        storage_keys = await _delete_ingested_email_tree(session, email_record)
        all_storage_keys.extend(storage_keys)
        deleted += 1
    await session.commit()
    for storage_key in all_storage_keys:
        try:
            await delete_file(storage_key)
        except FileNotFoundError:
            continue
    return {"deleted": deleted}


@router.get("/attachments/{attachment_id}/file")
async def get_attachment_file(
    attachment_id: int,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> Response:
    attachment_result = await session.execute(
        select(EmailAttachment)
        .where(EmailAttachment.id == attachment_id)
        .options(selectinload(EmailAttachment.email))
    )
    attachment = attachment_result.scalar_one_or_none()
    if attachment is None or attachment.email.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    try:
        file_bytes = await read_file(attachment.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment file not found") from exc

    return Response(
        content=file_bytes,
        media_type=attachment.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{attachment.filename}"',
        },
    )


@router.post("/timesheets/reapply-mappings", response_model=MappingReapplyResult)
async def reapply_sender_mappings(
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    mappings_result = await session.execute(
        select(EmailSenderMapping).where(EmailSenderMapping.tenant_id == current_user.tenant_id)
    )
    mappings = list(mappings_result.scalars().all())

    users_result = await session.execute(
        select(User).where(User.tenant_id == current_user.tenant_id)
    )
    users = list(users_result.scalars().all())

    clients_result = await session.execute(
        select(Client).where(Client.tenant_id == current_user.tenant_id)
    )
    clients = list(clients_result.scalars().all())

    unresolved_result = await session.execute(
        select(IngestionTimesheet)
        .where(
            (IngestionTimesheet.tenant_id == current_user.tenant_id)
            & (
                (IngestionTimesheet.client_id.is_(None))
                | (IngestionTimesheet.employee_id.is_(None))
            )
        )
        .options(selectinload(IngestionTimesheet.email))
    )
    unresolved_timesheets = list(unresolved_result.scalars().all())

    def _find_mapping(sender_email: str) -> EmailSenderMapping | None:
        normalized_email = sender_email.strip().lower()
        domain = normalized_email.split("@", 1)[1] if "@" in normalized_email else ""
        for mapping in mappings:
            normalized_value = _normalize_match_value(mapping.match_type, mapping.match_value)
            if mapping.match_type == SenderMatchType.email and normalized_value == normalized_email:
                return mapping
        for mapping in mappings:
            normalized_value = _normalize_match_value(mapping.match_type, mapping.match_value)
            if mapping.match_type == SenderMatchType.domain and normalized_value == domain:
                return mapping
        return None

    updated = 0
    for timesheet in unresolved_timesheets:
        sender_email = timesheet.email.sender_email if timesheet.email else ""
        mapping = _find_mapping(sender_email) if sender_email else None
        extracted_data = timesheet.extracted_data or {}
        llm_suggestions = timesheet.llm_match_suggestions or {}

        employee_id = timesheet.employee_id
        client_id = timesheet.client_id

        if employee_id is None:
            if mapping and mapping.employee_id:
                employee_id = mapping.employee_id
            else:
                employee_suggestion = llm_suggestions.get("employee") or {}
                if float(employee_suggestion.get("confidence", 0) or 0) >= 0.85:
                    employee_id = employee_suggestion.get("suggested_id")
                elif extracted_data.get("employee_name"):
                    normalized_name = extracted_data["employee_name"].strip().lower()
                    matched_user = next(
                        (user for user in users if user.full_name.strip().lower() == normalized_name),
                        None,
                    )
                    if matched_user:
                        employee_id = matched_user.id

        if client_id is None:
            if mapping and mapping.client_id:
                client_id = mapping.client_id
            else:
                client_suggestion = llm_suggestions.get("client") or {}
                if float(client_suggestion.get("confidence", 0) or 0) >= 0.85:
                    client_id = client_suggestion.get("suggested_id")
                elif extracted_data.get("client_name") or extracted_data.get("client"):
                    extracted_client_name = (
                        extracted_data.get("client_name")
                        or extracted_data.get("client")
                        or ""
                    ).strip().lower()
                    matched_client = next(
                        (client for client in clients if client.name.strip().lower() == extracted_client_name),
                        None,
                    )
                    if matched_client:
                        client_id = matched_client.id

        if employee_id != timesheet.employee_id or client_id != timesheet.client_id:
            timesheet.employee_id = employee_id
            timesheet.client_id = client_id
            updated += 1

    await session.commit()
    return {"checked": len(unresolved_timesheets), "updated": updated}


@router.get("/timesheets", response_model=list[IngestionTimesheetSummary])
async def list_review_timesheets(
    status_filter: str | None = Query(None),
    client_id: int | None = Query(None),
    employee_id: int | None = Query(None),
    email_id: int | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    timesheets = await list_ingestion_timesheets(
        session=session,
        tenant_id=current_user.tenant_id,
        status=status_filter,
        client_id=client_id,
        employee_id=employee_id,
        email_id=email_id,
        search=search,
        limit=limit,
        offset=offset,
    )
    # Pre-compute set of sender emails that have at least one rejected timesheet
    from sqlalchemy import distinct
    from app.models.ingested_email import IngestedEmail as _IngestedEmail
    rejected_senders_result = await session.execute(
        select(distinct(_IngestedEmail.sender_email))
        .join(IngestionTimesheet, IngestionTimesheet.email_id == _IngestedEmail.id)
        .where(
            (IngestionTimesheet.tenant_id == current_user.tenant_id) &
            (IngestionTimesheet.status == IngestionTimesheetStatus.rejected)
        )
    )
    rejected_sender_set = {row for row in rejected_senders_result.scalars().all() if row}
    return [_timesheet_to_summary(timesheet, rejected_sender_set) for timesheet in timesheets]


@router.get("/timesheets/{timesheet_id}", response_model=IngestionTimesheetDetail)
async def get_review_timesheet(
    timesheet_id: int,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    timesheet = await get_ingestion_timesheet(session, timesheet_id, current_user.tenant_id)
    if not timesheet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")
    return _timesheet_to_detail(timesheet)


@router.patch("/timesheets/{timesheet_id}/data")
async def update_timesheet_data(
    timesheet_id: int,
    body: TimesheetDataUpdate,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    timesheet = await get_ingestion_timesheet(session, timesheet_id, current_user.tenant_id)
    if not timesheet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")
    if timesheet.status == IngestionTimesheetStatus.approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot edit an approved timesheet",
        )

    updates = body.model_dump(exclude_unset=True)
    serialized_updates = body.model_dump(mode="json", exclude_unset=True)
    await _validate_employee(session, current_user, updates.get("employee_id"))
    await _validate_client(session, current_user, updates.get("client_id"))

    previous = {
        "employee_id": timesheet.employee_id,
        "client_id": timesheet.client_id,
        "period_start": str(timesheet.period_start) if timesheet.period_start else None,
        "period_end": str(timesheet.period_end) if timesheet.period_end else None,
        "total_hours": str(timesheet.total_hours) if timesheet.total_hours is not None else None,
        "internal_notes": timesheet.internal_notes,
    }

    for key, value in updates.items():
        setattr(timesheet, key, value)

    timesheet.corrected_data = {
        **(timesheet.corrected_data or {}),
        **serialized_updates,
    }
    timesheet.status = IngestionTimesheetStatus.under_review
    timesheet.reviewer_id = current_user.id
    timesheet.updated_at = datetime.now(timezone.utc)

    await write_audit_log(
        session,
        timesheet_id,
        current_user.id,
        "field_updated",
        previous_value=previous,
        new_value=serialized_updates,
    )
    await session.commit()
    return {"status": "updated"}


@router.post(
    "/timesheets/{timesheet_id}/line-items",
    response_model=LineItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_line_item(
    timesheet_id: int,
    body: LineItemCreate,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> IngestionTimesheetLineItem:
    timesheet = await get_ingestion_timesheet(session, timesheet_id, current_user.tenant_id)
    if not timesheet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")
    if timesheet.status == IngestionTimesheetStatus.approved:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot edit an approved timesheet")

    await _validate_project(session, current_user, body.project_id)
    item = IngestionTimesheetLineItem(
        ingestion_timesheet_id=timesheet_id,
        work_date=body.work_date,
        hours=body.hours,
        description=body.description,
        project_code=body.project_code,
        project_id=body.project_id,
    )
    session.add(item)
    timesheet.status = IngestionTimesheetStatus.under_review
    timesheet.reviewer_id = current_user.id
    timesheet.updated_at = datetime.now(timezone.utc)
    await write_audit_log(
        session,
        timesheet_id,
        current_user.id,
        "line_item_added",
        new_value=body.model_dump(mode="json"),
    )
    await session.commit()
    await session.refresh(item)
    return item


@router.patch("/timesheets/{timesheet_id}/line-items/{item_id}", response_model=LineItemRead)
async def update_line_item(
    timesheet_id: int,
    item_id: int,
    body: LineItemUpdate,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> IngestionTimesheetLineItem:
    timesheet = await get_ingestion_timesheet(session, timesheet_id, current_user.tenant_id)
    if not timesheet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")
    if timesheet.status == IngestionTimesheetStatus.approved:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot edit an approved timesheet")

    result = await session.execute(
        select(IngestionTimesheetLineItem).where(
            (IngestionTimesheetLineItem.id == item_id) &
            (IngestionTimesheetLineItem.ingestion_timesheet_id == timesheet_id)
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line item not found")

    updates = body.model_dump(exclude_unset=True)
    await _validate_project(session, current_user, updates.get("project_id"))
    if not item.is_corrected:
        item.original_value = {
            "work_date": str(item.work_date),
            "hours": str(item.hours),
            "description": item.description,
            "project_code": item.project_code,
            "project_id": item.project_id,
        }
    item.is_corrected = True
    for key, value in updates.items():
        setattr(item, key, value)

    timesheet.status = IngestionTimesheetStatus.under_review
    timesheet.reviewer_id = current_user.id
    timesheet.updated_at = datetime.now(timezone.utc)
    await write_audit_log(
        session,
        timesheet_id,
        current_user.id,
        "line_item_updated",
        previous_value=item.original_value,
        new_value=body.model_dump(mode="json", exclude_unset=True),
    )
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/timesheets/{timesheet_id}/line-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_line_item(
    timesheet_id: int,
    item_id: int,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> None:
    timesheet = await get_ingestion_timesheet(session, timesheet_id, current_user.tenant_id)
    if not timesheet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")
    if timesheet.status == IngestionTimesheetStatus.approved:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot edit an approved timesheet")

    result = await session.execute(
        select(IngestionTimesheetLineItem).where(
            (IngestionTimesheetLineItem.id == item_id) &
            (IngestionTimesheetLineItem.ingestion_timesheet_id == timesheet_id)
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line item not found")

    deleted_payload = {
        "work_date": str(item.work_date),
        "hours": str(item.hours),
        "description": item.description,
        "project_code": item.project_code,
        "project_id": item.project_id,
    }
    await session.delete(item)
    timesheet.status = IngestionTimesheetStatus.under_review
    timesheet.reviewer_id = current_user.id
    timesheet.updated_at = datetime.now(timezone.utc)
    await write_audit_log(
        session,
        timesheet_id,
        current_user.id,
        "line_item_deleted",
        previous_value=deleted_payload,
    )
    await session.commit()


@router.post("/timesheets/{timesheet_id}/approve", response_model=ApprovalResult)
async def approve_timesheet(
    timesheet_id: int,
    body: ApproveRequest,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    timesheet = await get_ingestion_timesheet(session, timesheet_id, current_user.tenant_id)
    if not timesheet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")
    if timesheet.status == IngestionTimesheetStatus.approved:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Timesheet is already approved")
    if not timesheet.employee_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot approve: no employee assigned to this timesheet",
        )


    now = datetime.now(timezone.utc)
    created_entry_ids: list[int] = []
    project_ids_used: set[int] = set()
    skipped_line_items: list[dict[str, str]] = []

    # Check for existing time entries on the same dates for this employee
    line_item_dates = [item.work_date for item in timesheet.line_items if item.work_date]
    overlapping_dates: list[str] = []
    if line_item_dates:
        from sqlalchemy import func as sa_func
        overlap_result = await session.execute(
            select(TimeEntry.entry_date, sa_func.count(TimeEntry.id)).where(
                (TimeEntry.user_id == timesheet.employee_id)
                & (TimeEntry.tenant_id == current_user.tenant_id)
                & (TimeEntry.entry_date.in_(line_item_dates))
            ).group_by(TimeEntry.entry_date)
        )
        overlapping_dates = [row[0].isoformat() for row in overlap_result.all()]

    for item in timesheet.line_items:
        if getattr(item, "is_rejected", False):
            skipped_line_items.append({
                "line_item_id": str(item.id),
                "work_date": str(item.work_date),
                "reason": "line_item_rejected",
            })
            continue
        project_id = await _resolve_project_for_line_item(session, current_user, item)
        if project_id is None:
            skipped_line_items.append({
                "line_item_id": str(item.id),
                "work_date": str(item.work_date),
                "reason": "missing_project_assignment",
            })
            continue
        entry = TimeEntry(
            tenant_id=current_user.tenant_id,
            user_id=timesheet.employee_id,
            project_id=project_id,
            task_id=None,
            entry_date=item.work_date,
            hours=item.hours,
            description=item.description or "",
            is_billable=True,
            status=TimeEntryStatus.APPROVED,
            submitted_at=now,
            approved_by=current_user.id,
            approved_at=now,
            created_by=current_user.id,
            updated_by=current_user.id,
            ingestion_timesheet_id=str(timesheet.id),
            ingestion_line_item_id=str(item.id),
            ingestion_approved_by_name=current_user.full_name,
            ingestion_source_tenant=str(current_user.tenant_id),
        )
        session.add(entry)
        await session.flush()
        created_entry_ids.append(entry.id)
        project_ids_used.add(project_id)

    timesheet.status = IngestionTimesheetStatus.approved
    timesheet.reviewer_id = current_user.id
    timesheet.reviewed_at = now
    timesheet.updated_at = now
    timesheet.time_entries_created = len(created_entry_ids) > 0
    await write_audit_log(
        session,
        timesheet_id,
        current_user.id,
        "approved",
        new_value={
            "time_entries_created": len(created_entry_ids),
            "project_ids": list(project_ids_used),
            "skipped_line_items": skipped_line_items,
            "reviewer": current_user.full_name,
        },
        comment=body.comment,
    )
    await session.commit()

    return {
        "ingestion_timesheet_id": timesheet_id,
        "time_entries_created": len(created_entry_ids),
        "employee_id": timesheet.employee_id,
        "project_ids": sorted(project_ids_used),
        "status": "approved",
        "overlapping_entries_count": len(overlapping_dates),
        "overlapping_dates": overlapping_dates,
    }


@router.post("/timesheets/{timesheet_id}/reject", status_code=status.HTTP_200_OK)
async def reject_timesheet(
    timesheet_id: int,
    body: RejectRequest,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    timesheet = await get_ingestion_timesheet(session, timesheet_id, current_user.tenant_id)
    if not timesheet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")
    if timesheet.status == IngestionTimesheetStatus.approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reject an already approved timesheet",
        )

    now = datetime.now(timezone.utc)
    timesheet.status = IngestionTimesheetStatus.rejected
    timesheet.rejection_reason = body.reason
    timesheet.reviewer_id = current_user.id
    timesheet.reviewed_at = now
    timesheet.updated_at = now
    await write_audit_log(
        session,
        timesheet_id,
        current_user.id,
        "rejected",
        new_value={"reason": body.reason},
        comment=body.comment,
    )
    await session.commit()

    # Send rejection notification email to the contractor
    try:
        from app.services.email_service import send_email
        email_result = await session.execute(
            select(IngestedEmail).where(IngestedEmail.id == timesheet.email_id)
        )
        email_record = email_result.scalar_one_or_none()
        if email_record and email_record.sender_email:
            period_str = ""
            if timesheet.period_start and timesheet.period_end:
                period_str = (
                    f"{timesheet.period_start.strftime('%b %d')} – "
                    f"{timesheet.period_end.strftime('%b %d, %Y')}"
                )
            employee_name = (
                timesheet.employee.full_name
                if timesheet.employee else "Contractor"
            )
            subject = f"Timesheet Rejected — {period_str or email_record.subject or 'Your recent submission'}"
            body_text = (
                f"Dear {employee_name},\n\n"
                f"Your timesheet submission has been reviewed and rejected.\n\n"
                f"Period: {period_str or 'See original submission'}\n"
                f"Reason: {body.reason}\n\n"
                f"Please review the reason above, correct your timesheet, "
                f"and reply to this email with the corrected timesheet attached.\n\n"
                f"If you have any questions, please contact your project manager.\n\n"
                f"Regards,\nAcufy Platform"
            )
            await send_email(to_address=email_record.sender_email, subject=subject, body_text=body_text)
    except Exception as exc:
        logger.error("Failed to send rejection email: %s", exc)

    return {"status": "rejected", "reason": body.reason}


@router.post("/timesheets/{timesheet_id}/hold", status_code=status.HTTP_200_OK)
async def hold_timesheet(
    timesheet_id: int,
    body: HoldRequest,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    timesheet = await get_ingestion_timesheet(session, timesheet_id, current_user.tenant_id)
    if not timesheet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")

    timesheet.status = IngestionTimesheetStatus.on_hold
    timesheet.reviewer_id = current_user.id
    timesheet.updated_at = datetime.now(timezone.utc)
    await write_audit_log(
        session,
        timesheet_id,
        current_user.id,
        "placed_on_hold",
        comment=body.comment,
    )
    await session.commit()
    return {"status": "on_hold"}


@router.post(
    "/timesheets/{timesheet_id}/line-items/{item_id}/reject",
    status_code=status.HTTP_200_OK,
)
async def reject_line_item(
    timesheet_id: int,
    item_id: int,
    body: RejectRequest,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Reject a single line item within a staged timesheet."""
    timesheet = await get_ingestion_timesheet(session, timesheet_id, current_user.tenant_id)
    if not timesheet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")
    if timesheet.status == IngestionTimesheetStatus.approved:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify an approved timesheet")

    result = await session.execute(
        select(IngestionTimesheetLineItem).where(
            (IngestionTimesheetLineItem.id == item_id) &
            (IngestionTimesheetLineItem.ingestion_timesheet_id == timesheet_id)
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line item not found")

    item.is_rejected = True
    item.rejection_reason = body.reason
    timesheet.status = IngestionTimesheetStatus.under_review
    timesheet.reviewer_id = current_user.id
    timesheet.updated_at = datetime.now(timezone.utc)

    await write_audit_log(
        session, timesheet_id, current_user.id,
        "line_item_rejected",
        new_value={
            "line_item_id": item_id,
            "work_date": str(item.work_date),
            "reason": body.reason,
        },
    )
    await session.commit()
    return {"status": "rejected", "line_item_id": item_id}


@router.post(
    "/timesheets/{timesheet_id}/line-items/{item_id}/unreject",
    status_code=status.HTTP_200_OK,
)
async def unreject_line_item(
    timesheet_id: int,
    item_id: int,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Restore a previously rejected line item."""
    timesheet = await get_ingestion_timesheet(session, timesheet_id, current_user.tenant_id)
    if not timesheet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")
    if timesheet.status == IngestionTimesheetStatus.approved:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify an approved timesheet")

    result = await session.execute(
        select(IngestionTimesheetLineItem).where(
            (IngestionTimesheetLineItem.id == item_id) &
            (IngestionTimesheetLineItem.ingestion_timesheet_id == timesheet_id)
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line item not found")

    item.is_rejected = False
    item.rejection_reason = None
    timesheet.status = IngestionTimesheetStatus.under_review
    timesheet.reviewer_id = current_user.id
    timesheet.updated_at = datetime.now(timezone.utc)

    await write_audit_log(
        session, timesheet_id, current_user.id,
        "line_item_unrejected",
        new_value={"line_item_id": item_id, "work_date": str(item.work_date)},
    )
    await session.commit()
    return {"status": "restored", "line_item_id": item_id}


@router.post("/timesheets/{timesheet_id}/revert-rejection", status_code=status.HTTP_200_OK)
async def revert_timesheet_rejection(
    timesheet_id: int,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Revert a rejected ingested timesheet back to pending status."""
    timesheet = await get_ingestion_timesheet(session, timesheet_id, current_user.tenant_id)
    if not timesheet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")
    if timesheet.status != IngestionTimesheetStatus.rejected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only rejected timesheets can be reverted")

    timesheet.status = IngestionTimesheetStatus.pending
    timesheet.rejection_reason = None
    timesheet.reviewer_id = current_user.id
    timesheet.updated_at = datetime.now(timezone.utc)

    await write_audit_log(
        session, timesheet_id, current_user.id,
        "rejection_reverted",
        new_value={"reverted_by": current_user.full_name},
    )
    await session.commit()
    return {"status": "pending"}


@router.post("/timesheets/{timesheet_id}/draft-comment", response_model=DraftCommentResponse)
async def draft_timesheet_comment(
    timesheet_id: int,
    body: DraftCommentRequest,
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    timesheet = await get_ingestion_timesheet(session, timesheet_id, current_user.tenant_id)
    if not timesheet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")

    draft = await draft_comment(
        timesheet_summary={
            "employee_id": timesheet.employee_id,
            "period_start": str(timesheet.period_start) if timesheet.period_start else None,
            "period_end": str(timesheet.period_end) if timesheet.period_end else None,
            "total_hours": str(timesheet.total_hours) if timesheet.total_hours is not None else None,
        },
        anomalies=timesheet.llm_anomalies or [],
        seed_text=body.seed_text,
    )
    return {"draft": draft}


# ─── Test Simulation ─────────────────────────────────────────────────────────

@router.post("/simulate-ingestion", status_code=status.HTTP_200_OK)
async def simulate_ingestion(
    current_user=Depends(require_can_review),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """
    DEV/TEST ONLY: Inject sample timesheets from sample_timesheets/ folder
    directly into the ingestion pipeline, simulating email attachments.
    Each file becomes a separate IngestedEmail + attachment, then runs
    through the full extraction pipeline.
    """
    import logging
    import mimetypes
    from pathlib import Path
    from app.services.ingestion_pipeline import process_email

    logger = logging.getLogger(__name__)

    # Find sample_timesheets folder (relative to project root)
    sample_dir = Path(__file__).resolve().parents[3] / "sample_timesheets"
    if not sample_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"sample_timesheets/ folder not found at {sample_dir}",
        )

    files = sorted(sample_dir.iterdir())
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files found in sample_timesheets/",
        )

    results = []
    for filepath in files:
        if filepath.is_dir() or filepath.name.startswith("."):
            continue

        content = filepath.read_bytes()
        mime_type = mimetypes.guess_type(filepath.name)[0] or "application/octet-stream"

        # Build a fake raw_message dict that mimics what the email parser returns
        fake_message = {
            "message_id": f"<simulate-{filepath.stem}-{datetime.now(timezone.utc).timestamp():.0f}@test>",
            "subject": f"Timesheets - {filepath.stem}",
            "sender_email": "simulator@test.local",
            "sender_name": "Test Simulator",
            "recipients": [],
            "body_text": f"Simulated ingestion of {filepath.name}",
            "body_html": None,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "raw_headers": {},
            "attachments": [
                {
                    "filename": filepath.name,
                    "mime_type": mime_type,
                    "content": content,
                    "is_processable": True,
                    "likely_timesheet": True,
                }
            ],
        }

        try:
            pipeline_result = await process_email(
                raw_message=fake_message,
                mailbox_id=0,
                tenant_id=current_user.tenant_id,
                session=session,
            )
            results.append({
                "file": filepath.name,
                "email_id": pipeline_result.email_id,
                "skipped": pipeline_result.skipped,
                "skip_reason": pipeline_result.skip_reason,
                "timesheets_created": pipeline_result.timesheets_created,
                "errors": pipeline_result.errors,
            })
        except Exception as exc:
            logger.error("Simulate failed for %s: %s", filepath.name, exc)
            results.append({
                "file": filepath.name,
                "email_id": None,
                "skipped": True,
                "skip_reason": f"error: {exc}",
                "timesheets_created": 0,
                "errors": [str(exc)],
            })

    staged = sum(1 for r in results if not r["skipped"])
    skipped = sum(1 for r in results if r["skipped"])
    total_timesheets = sum(r["timesheets_created"] for r in results)

    return {
        "status": "completed",
        "files_processed": len(results),
        "staged": staged,
        "skipped": skipped,
        "total_timesheets_created": total_timesheets,
        "details": results,
    }
