"""
Ingestion pipeline orchestrator.
Stages ingestion data only. It does not create time_entries.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.project import Project
from app.models.email_attachment import EmailAttachment, ExtractionStatus
from app.models.ingested_email import IngestedEmail
from app.models.ingestion_timesheet import (
    IngestionAuditActorType,
    IngestionAuditLog,
    IngestionTimesheet,
    IngestionTimesheetLineItem,
    IngestionTimesheetStatus,
)
from app.models.user import User, UserRole
from app.services.email_parser import ParsedAttachment, _is_likely_timesheet_filename, parse_email
from app.services.extraction import extract_text
from app.services.llm_ingestion import (
    classify_email,
    detect_anomalies,
    extract_timesheet_data,
)
from app.services.storage import delete_file, read_file, save_file

logger = logging.getLogger(__name__)


def _has_candidate_timesheet_attachment(
    attachments: list[ParsedAttachment],
) -> bool:
    return any(attachment.is_processable for attachment in attachments)


def _persist_skip_metadata(
    email_record: IngestedEmail,
    classification: dict | None,
    reason: str,
    detail: str | None = None,
    errors: list[str] | None = None,
) -> None:
    payload = dict(classification or {})
    payload["pipeline_skip_reason"] = reason
    if detail:
        payload["pipeline_skip_detail"] = detail
    if errors:
        payload["pipeline_errors"] = errors
    email_record.llm_classification = payload


async def _drop_email_and_attachments(
    email_record: IngestedEmail,
    attachment_records: list[tuple[ParsedAttachment, EmailAttachment]],
    session: AsyncSession,
) -> list[str]:
    storage_keys: list[str] = []
    for _, attachment_record in attachment_records:
        if attachment_record.storage_key:
            storage_keys.append(attachment_record.storage_key)
        await session.delete(attachment_record)

    await session.delete(email_record)
    await session.flush()
    return storage_keys


async def _cleanup_storage_keys(storage_keys: list[str]) -> None:
    for storage_key in storage_keys:
        try:
            await delete_file(storage_key)
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.warning("Failed to delete discarded attachment file %s: %s", storage_key, exc)


@dataclass
class PipelineResult:
    skipped: bool = False
    skip_reason: str | None = None
    skip_detail: str | None = None
    email_id: int | None = None
    message_id: str | None = None
    subject: str | None = None
    sender_email: str | None = None
    timesheets_created: int = 0
    errors: list[str] = field(default_factory=list)


def _coerce_received_at(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _build_parsed_email(raw_message: dict):
    if "raw" in raw_message:
        return parse_email(raw_message["raw"])

    attachments = [
        ParsedAttachment(
            filename=attachment["filename"],
            mime_type=attachment["mime_type"],
            content=attachment["content"],
            is_processable=attachment.get("is_processable", attachment.get("is_timesheet", False)),
            likely_timesheet=attachment.get(
                "likely_timesheet",
                _is_likely_timesheet_filename(attachment.get("filename", "")),
            ),
        )
        for attachment in raw_message.get("attachments", [])
    ]

    recipients = raw_message.get("recipients") or []
    if isinstance(recipients, dict):
        recipients = recipients.get("to") or []

    from app.services.email_parser import ParsedEmail

    return ParsedEmail(
        message_id=raw_message.get("message_id", ""),
        subject=raw_message.get("subject", "") or "",
        sender_email=(raw_message.get("sender_email", "") or "").lower().strip(),
        sender_name=raw_message.get("sender_name", "") or "",
        recipients=recipients if isinstance(recipients, list) else [],
        body_text=raw_message.get("body_text", "") or "",
        body_html=raw_message.get("body_html", "") or "",
        received_at=_coerce_received_at(raw_message.get("received_at")),
        has_attachments=bool(attachments),
        raw_headers=raw_message.get("raw_headers") or {},
        attachments=attachments,
    )


async def process_email(
    raw_message: dict,
    mailbox_id: int,
    tenant_id: int,
    session: AsyncSession,
) -> PipelineResult:
    """
    Process a single raw email through the staging ingestion pipeline.
    """
    result = PipelineResult()
    message_id = raw_message["message_id"]
    result.message_id = message_id

    try:
        parsed = _build_parsed_email(raw_message)
        result.subject = parsed.subject
        result.sender_email = parsed.sender_email
    except Exception as exc:
        result.errors.append(f"Email parsing failed: {exc}")
        return result


    existing = await session.execute(
        select(IngestedEmail).where(
            (IngestedEmail.tenant_id == tenant_id)
            & (IngestedEmail.message_id == message_id)
        )
    )
    existing_email = existing.scalar_one_or_none()
    if existing_email:
        result.skipped = True
        result.skip_reason = "already_ingested"
        result.skip_detail = "This email was already ingested earlier and was not retried."
        result.email_id = existing_email.id
        result.subject = result.subject or existing_email.subject
        result.sender_email = result.sender_email or existing_email.sender_email
        return result

    saved_storage_keys: list[str] = []

    now = datetime.now(timezone.utc)
    email_record = IngestedEmail(
        tenant_id=tenant_id,
        mailbox_id=mailbox_id,
        message_id=message_id,
        subject=parsed.subject,
        sender_email=parsed.sender_email,
        sender_name=parsed.sender_name,
        forwarded_from_email=parsed.forwarded_from_email,
        forwarded_from_name=parsed.forwarded_from_name,
        recipients={"to": parsed.recipients},
        body_text=parsed.body_text,
        body_html=parsed.body_html,
        received_at=parsed.received_at,
        fetched_at=now,
        has_attachments=parsed.has_attachments,
        raw_headers=parsed.raw_headers,
        # Coerced to list because SQLAlchemy's JSON type serializes tuples as
        # arrays but the round-tripped Python value matters for equality
        # checks in tests and downstream code.
        chain_senders=list(parsed.chain_senders) if parsed.chain_senders else None,
    )
    session.add(email_record)
    await session.flush()
    result.email_id = email_record.id

    attachment_records: list[tuple[ParsedAttachment, EmailAttachment]] = []
    for attachment in parsed.attachments:
        try:
            storage_key = await save_file(attachment.content, attachment.filename)
            saved_storage_keys.append(storage_key)
            attachment_record = EmailAttachment(
                email_id=email_record.id,
                filename=attachment.filename,
                mime_type=attachment.mime_type,
                size_bytes=len(attachment.content),
                storage_key=storage_key,
                is_timesheet=attachment.is_processable,
                extraction_status=ExtractionStatus.pending,
                created_at=now,
            )
            session.add(attachment_record)
            attachment_records.append((attachment, attachment_record))
        except Exception as exc:
            logger.warning("Failed to save attachment %s: %s", attachment.filename, exc)
            result.errors.append(f"Attachment save failed: {attachment.filename}")

    await session.flush()

    try:
        classification = await classify_email(
            subject=parsed.subject or "",
            body_text=parsed.body_text or "",
            attachment_filenames=[a.filename for a in parsed.attachments],
            attachment_mime_types=[a.mime_type for a in parsed.attachments],
            has_candidate_attachment=_has_candidate_timesheet_attachment(parsed.attachments),
        )
        email_record.llm_classification = classification
    except Exception as exc:
        logger.warning("Email classification failed: %s", exc)
        classification = {
            "is_timesheet_email": False,
            "intent": "unknown",
            "confidence": 0.0,
        }

    has_candidates = _has_candidate_timesheet_attachment(parsed.attachments)
    is_timesheet = classification.get("is_timesheet_email", True)
    intent = classification.get("intent", "unrelated")
    confidence = float(classification.get("confidence", 0.0) or 0.0)

    SUBMISSION_INTENTS = {
        "new_submission", "resubmission", "correction",
        "submission", "timesheet_submission",
    }

    # Skip only when: not a timesheet AND no submission intent AND no attachments
    if not is_timesheet and intent not in SUBMISSION_INTENTS and not has_candidates:
        detail = f"Classifier intent was {intent}."
        storage_keys = await _drop_email_and_attachments(email_record, attachment_records, session)
        await session.commit()
        await _cleanup_storage_keys(storage_keys)
        result.skipped = True
        result.skip_reason = f"not_timesheet_email:{intent}"
        result.skip_detail = f"{detail} Discarded as non-actionable."
        result.email_id = None
        return result

    # Also skip low-confidence emails with no attachments
    if confidence < 0.3 and not has_candidates:
        detail = f"Low confidence ({confidence:.2f}) and no candidate attachments."
        storage_keys = await _drop_email_and_attachments(email_record, attachment_records, session)
        await session.commit()
        await _cleanup_storage_keys(storage_keys)
        result.skipped = True
        result.skip_reason = f"low_confidence_no_attachments:{confidence:.2f}"
        result.skip_detail = f"{detail} Discarded as non-actionable."
        result.email_id = None
        return result

    candidate_attachment_count = 0
    failed_attachment_count = 0
    for attachment, attachment_record in attachment_records:
        if not attachment.is_processable:
            continue

        candidate_attachment_count += 1
        try:
            count = await _process_timesheet_attachment(
                attachment=attachment,
                attachment_record=attachment_record,
                email_record=email_record,
                tenant_id=tenant_id,
                session=session,
                now=now,
            )
            result.timesheets_created += count
        except Exception as exc:
            logger.error("Failed to process timesheet attachment %s: %s", attachment.filename, exc)
            attachment_record.extraction_status = ExtractionStatus.failed
            attachment_record.extraction_error = str(exc)
            result.errors.append(f"Timesheet processing failed: {attachment.filename}: {exc}")
            failed_attachment_count += 1

    if result.timesheets_created == 0:
        result.skipped = True
        if candidate_attachment_count == 0:
            result.skip_reason = "no_candidate_timesheet_attachment"
            result.skip_detail = "No attachment matched the current timesheet attachment detection rules."
        elif failed_attachment_count == candidate_attachment_count:
            result.skip_reason = "attachment_extraction_failed"
            result.skip_detail = "All candidate timesheet attachments failed during extraction."
        else:
            result.skip_reason = "no_structured_timesheet_data"
            result.skip_detail = "Attachments were inspected but no structured timesheet rows were created."

        _persist_skip_metadata(
            email_record,
            email_record.llm_classification,
            result.skip_reason,
            result.skip_detail,
            result.errors,
        )

    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        # Clean up orphaned storage files
        for key in saved_storage_keys:
            try:
                await delete_file(key)
            except Exception:
                logger.warning("Failed to clean up orphaned storage file: %s", key)
        result.errors.append(f"Database commit failed: {exc}")

    return result


async def _clear_derived_records(
    session: AsyncSession,
    email_id: int,
    attachment_ids: list[int] | None = None,
) -> None:
    timesheet_query = select(IngestionTimesheet).where(IngestionTimesheet.email_id == email_id)
    if attachment_ids:
        timesheet_query = timesheet_query.where(IngestionTimesheet.attachment_id.in_(attachment_ids))

    timesheet_result = await session.execute(timesheet_query)
    timesheets = list(timesheet_result.scalars().all())

    # Check for approved timesheets that have already been synced to time entries
    approved_synced = [
        ts for ts in timesheets
        if ts.status == IngestionTimesheetStatus.approved and ts.time_entries_created
    ]
    if approved_synced:
        raise ValueError(
            f"Cannot reprocess: {len(approved_synced)} approved timesheet(s) with "
            f"time_entries_created=True exist for email_id={email_id}. "
            "Please manually handle these before reprocessing."
        )

    # Only delete non-approved or non-synced timesheets
    deletable = [
        ts for ts in timesheets
        if not (ts.status == IngestionTimesheetStatus.approved and ts.time_entries_created)
    ]
    timesheet_ids = [timesheet.id for timesheet in deletable]

    if timesheet_ids:
        audit_result = await session.execute(
            select(IngestionAuditLog).where(IngestionAuditLog.ingestion_timesheet_id.in_(timesheet_ids))
        )
        for audit in audit_result.scalars().all():
            await session.delete(audit)

        line_item_result = await session.execute(
            select(IngestionTimesheetLineItem).where(
                IngestionTimesheetLineItem.ingestion_timesheet_id.in_(timesheet_ids)
            )
        )
        for line_item in line_item_result.scalars().all():
            await session.delete(line_item)

        for timesheet in deletable:
            await session.delete(timesheet)


async def reprocess_stored_email(
    email_id: int,
    tenant_id: int,
    session: AsyncSession,
    attachment_ids: list[int] | None = None,
) -> PipelineResult:
    result = PipelineResult(email_id=email_id)

    email_result = await session.execute(
        select(IngestedEmail).where(
            (IngestedEmail.id == email_id) & (IngestedEmail.tenant_id == tenant_id)
        )
    )
    email_record = email_result.scalar_one_or_none()
    if email_record is None:
        result.skipped = True
        result.skip_reason = "email_not_found"
        result.skip_detail = "The stored email could not be found for reprocessing."
        return result

    result.message_id = email_record.message_id
    result.subject = email_record.subject
    result.sender_email = email_record.sender_email

    original_updated_at = email_record.updated_at if hasattr(email_record, 'updated_at') else None

    attachment_query = select(EmailAttachment).where(EmailAttachment.email_id == email_id)
    if attachment_ids:
        attachment_query = attachment_query.where(EmailAttachment.id.in_(attachment_ids))

    attachment_result = await session.execute(attachment_query)
    stored_attachments = list(attachment_result.scalars().all())
    if not stored_attachments:
        result.skipped = True
        result.skip_reason = "no_reprocessable_attachments"
        result.skip_detail = "No stored attachments matched this reprocess request."
        return result

    # Re-check the email hasn't been modified by a concurrent reprocess
    await session.refresh(email_record)
    if original_updated_at and hasattr(email_record, 'updated_at') and email_record.updated_at != original_updated_at:
        raise ValueError("Email has been modified by another process, aborting reprocess")

    await _clear_derived_records(session, email_id, [attachment.id for attachment in stored_attachments] if attachment_ids else None)

    parsed_attachments: list[tuple[ParsedAttachment, EmailAttachment]] = []
    for attachment_record in stored_attachments:
        attachment_record.extraction_method = None
        attachment_record.extraction_status = ExtractionStatus.pending
        attachment_record.extraction_error = None
        attachment_record.raw_extracted_text = None
        attachment_record.spreadsheet_preview = None
        attachment_record.rendered_html = None
        try:
            content = await read_file(attachment_record.storage_key)
        except Exception as exc:
            attachment_record.extraction_status = ExtractionStatus.failed
            attachment_record.extraction_error = str(exc)
            result.errors.append(f"Attachment read failed: {attachment_record.filename}: {exc}")
            continue

        parsed_attachments.append(
            (
                ParsedAttachment(
                    filename=attachment_record.filename,
                    mime_type=attachment_record.mime_type,
                    content=content,
                    is_processable=attachment_record.is_timesheet,
                    likely_timesheet=_is_likely_timesheet_filename(attachment_record.filename),
                ),
                attachment_record,
            )
        )

    try:
        classification = await classify_email(
            subject=email_record.subject or "",
            body_text=email_record.body_text or "",
            attachment_filenames=[attachment_record.filename for attachment_record in stored_attachments],
            sender_email=email_record.sender_email,
            attachment_mime_types=[attachment_record.mime_type for attachment_record in stored_attachments],
            has_candidate_attachment=any(attachment.is_processable for attachment, _ in parsed_attachments),
        )
        if (
            not classification.get("is_timesheet_email", True)
            and any(attachment.is_processable for attachment, _ in parsed_attachments)
        ):
            classification = {
                **classification,
                "is_timesheet_email": True,
                "intent": classification.get("intent") or "attachment_review",
                "reasoning": (
                    f"{classification.get('reasoning', 'Classifier marked unrelated.')} "
                    "Continuing because the stored email includes a likely timesheet attachment."
                ).strip(),
            }
    except Exception as exc:
        logger.warning("Stored email classification failed: %s", exc)
        classification = {"is_timesheet_email": True, "intent": "unknown"}
    email_record.llm_classification = classification

    candidate_attachment_count = 0
    failed_attachment_count = 0
    now = datetime.now(timezone.utc)

    for attachment, attachment_record in parsed_attachments:
        if not attachment.is_processable:
            continue
        candidate_attachment_count += 1
        try:
            count = await _process_timesheet_attachment(
                attachment=attachment,
                attachment_record=attachment_record,
                email_record=email_record,
                tenant_id=tenant_id,
                session=session,
                now=now,
            )
            result.timesheets_created += count
        except Exception as exc:
            attachment_record.extraction_status = ExtractionStatus.failed
            attachment_record.extraction_error = str(exc)
            result.errors.append(f"Timesheet processing failed: {attachment.filename}: {exc}")
            failed_attachment_count += 1

    if result.timesheets_created == 0:
        result.skipped = True
        if candidate_attachment_count == 0:
            result.skip_reason = "no_candidate_timesheet_attachment"
            result.skip_detail = "No stored attachment matched the current timesheet attachment detection rules."
        elif failed_attachment_count == candidate_attachment_count:
            result.skip_reason = "attachment_extraction_failed"
            result.skip_detail = "All selected attachments failed during extraction."
        else:
            result.skip_reason = "no_structured_timesheet_data"
            result.skip_detail = "Selected attachments were processed, but no structured timesheet rows were created."
        _persist_skip_metadata(
            email_record,
            classification,
            result.skip_reason,
            result.skip_detail,
            result.errors,
        )

    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        result.errors.append(f"Database commit failed: {exc}")

    return result


def _normalize_line_items(
    line_items: list[dict],
    period_start: str | None,
    period_end: str | None,
) -> list[dict]:
    """
    Clean up LLM-extracted line items before staging:
    1. Remove zero or null hours
    2. Remove exact duplicates (same date + same hours)
    3. Remove entries outside the stated period (7-day tolerance)
    4. Sort by work_date
    """
    import datetime as _dt

    if not line_items:
        return []

    start_date = None
    end_date = None
    try:
        if period_start:
            start_date = _dt.date.fromisoformat(period_start)
    except (ValueError, TypeError):
        pass
    try:
        if period_end:
            end_date = _dt.date.fromisoformat(period_end)
    except (ValueError, TypeError):
        pass

    seen: set[tuple] = set()
    normalized: list[dict] = []

    for item in line_items:
        hours = item.get("hours")
        work_date_str = item.get("work_date")

        if not hours:
            continue
        try:
            hours_float = float(hours)
            if hours_float <= 0:
                continue
        except (ValueError, TypeError):
            continue

        if not work_date_str:
            continue
        try:
            work_date = _dt.date.fromisoformat(str(work_date_str))
        except (ValueError, TypeError):
            continue

        if start_date and work_date < start_date - _dt.timedelta(days=7):
            logger.info("Dropped line item outside period tolerance: work_date=%s, period=%s to %s", work_date, start_date, end_date)
            continue
        if end_date and work_date > end_date + _dt.timedelta(days=7):
            logger.info("Dropped line item outside period tolerance: work_date=%s, period=%s to %s", work_date, start_date, end_date)
            continue

        dedup_key = (str(work_date_str), str(hours_float), item.get("description", ""), item.get("project_code", ""))
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        normalized.append({**item, "work_date": str(work_date_str), "hours": hours_float})

    normalized.sort(key=lambda x: x.get("work_date", ""))
    return normalized


def _dedupe_extracted_timesheets(extracted_list: list[dict]) -> list[dict]:
    """Remove exact duplicate timesheet payloads produced by OCR/LLM extraction."""
    deduped: list[dict] = []
    seen: set[tuple] = set()

    for item in extracted_list:
        if not isinstance(item, dict):
            continue

        employee_name = " ".join(str(item.get("employee_name") or "").lower().split())
        client_name = " ".join(str(item.get("client_name") or item.get("client") or "").strip().lower().split())
        period_start = str(item.get("period_start") or "")
        period_end = str(item.get("period_end") or "")
        total_hours = str(item.get("total_hours") or "")

        raw_line_items = item.get("line_items")
        if isinstance(raw_line_items, list):
            line_items = sorted(
                (
                    str(li.get("work_date") or ""),
                    str(li.get("hours") or ""),
                    str(li.get("project_code") or ""),
                    str(li.get("description") or ""),
                )
                for li in raw_line_items
                if isinstance(li, dict)
            )
        else:
            line_items = []

        key = (employee_name, client_name, period_start, period_end, total_hours, tuple(line_items))
        if key in seen:
            continue

        seen.add(key)
        deduped.append(item)

    return deduped


async def _process_timesheet_attachment(
    attachment: ParsedAttachment,
    attachment_record: EmailAttachment,
    email_record: IngestedEmail,
    tenant_id: int,
    session: AsyncSession,
    now: datetime,
) -> int:
    """
    Process one attachment. Returns count of IngestionTimesheet records created.
    May create multiple records if the attachment contains multiple pay periods.
    """
    from datetime import date as date_type

    from app.services.summary_timesheet import looks_like_summary_sheet, parse_summary_timesheet

    attachment_record.extraction_status = ExtractionStatus.processing
    attachment_record.extraction_error = None

    # Pass the email's received date as reference so the Vision LLM resolves
    # year-less dates (e.g. "Mar 29 - Apr 04" with no year visible) to the
    # correct year rather than defaulting to an older training-data year.
    ref_date = (
        email_record.received_at.date().isoformat()
        if email_record and email_record.received_at
        else None
    )
    try:
        extraction = await extract_text(
            content=attachment.content,
            filename=attachment.filename,
            mime_type=attachment.mime_type,
            reference_date=ref_date,
        )
    except Exception as exc:
        logger.exception(
            "extract_text crashed for attachment %s (%s); marking failed",
            attachment.filename, attachment_record.id,
        )
        attachment_record.extraction_status = ExtractionStatus.failed
        attachment_record.extraction_error = f"{type(exc).__name__}: {exc}"
        attachment_record.extraction_method = None
        return 0
    attachment_record.raw_extracted_text = extraction.text
    attachment_record.spreadsheet_preview = extraction.spreadsheet_preview
    attachment_record.rendered_html = extraction.rendered_html
    attachment_record.extraction_method = (
        extraction.method if extraction.method != "failed" else None
    )
    attachment_record.extraction_status = (
        ExtractionStatus.completed if extraction.success else ExtractionStatus.failed
    )
    if extraction.error:
        attachment_record.extraction_error = extraction.error

    if not extraction.success:
        return 0

    # ── Summary sheet detection (run BEFORE LLM extraction) ──────────────────
    # If it looks like a summary sheet, parse it with the rule-based parser
    # (no LLM needed).
    extracted_list = None
    if looks_like_summary_sheet(extraction.text):
        # Use email received_at as reference date for better period inference, fallback to today
        reference_date = (email_record.received_at.date() if email_record and email_record.received_at else date_type.today())
        extracted_list = parse_summary_timesheet(extraction.text, reference_date)
        if extracted_list:
            logger.info(
                "Summary sheet detected for %s — using rule-based parser",
                attachment.filename,
            )
        else:
            logger.info(
                "Summary sheet detected for %s but parser returned empty — falling back to LLM",
                attachment.filename,
            )
            extracted_list = None  # Will fall through to Vision/LLM extraction below

    # ── Vision API result (structured JSON already) ───────────────────────────
    if extracted_list is None and extraction.vision_timesheets is not None:
        # Vision already returned structured timesheets — skip LLM extraction
        extracted_list = extraction.vision_timesheets
    # ── Standard LLM extraction ───────────────────────────────────────────────
    if extracted_list is None:
        extracted_list = await extract_timesheet_data(
            extraction.text,
            filename_hint=attachment.filename,
            likely_timesheet=attachment.likely_timesheet,
            reference_date=ref_date,
        )

    extracted_list = _dedupe_extracted_timesheets(extracted_list)

    if not extracted_list:
        return 0

    # Backfill contact_emails from the raw extracted text for any row where the
    # LLM returned nothing — regex is cheap and covers signatures the LLM may
    # have skipped.
    raw_text_emails = _extract_emails_from_text(extraction.text)
    for extracted_data in extracted_list:
        if isinstance(extracted_data, dict):
            existing = extracted_data.get("contact_emails")
            if not isinstance(existing, list) or not existing:
                extracted_data["contact_emails"] = raw_text_emails

    # ── Load known entities once for this attachment ──────────────────────────
    employees = await _load_known_employees(session, tenant_id)
    clients = await _load_known_clients(session, tenant_id)

    created_count = 0

    # ── One IngestionTimesheet per extracted timesheet in the list ────────────
    for extracted_data in extracted_list:
        if not isinstance(extracted_data, dict):
            continue

        # ── Employee resolution ────────────────────────────────────────────
        # Precedence (highest first):
        # 1. Name on the timesheet body (LLM employee_name)
        # 2. Name derived from the attachment filename
        # 3. Name on the forwarded-from header (when forwarded)
        # 4. Any email in the document body matching a known user's email
        # 5. Outer/forwarded sender → _resolve_or_create_external_user later
        employee_id = _fuzzy_match_employee(
            extracted_data.get("employee_name"), employees
        )

        # Filename-derived fallback: if LLM returned no employee_name, try to
        # recover one from the attachment filename (e.g. "Sridhar Kakulavaram
        # March 2026.pdf"). Stamped onto extracted_data so downstream auto-
        # create and the review UI both pick it up. Requires >=2 tokens.
        if not (extracted_data.get("employee_name") or "").strip():
            filename_name = _derive_name_from_filename(attachment.filename)
            if filename_name and len(filename_name.split()) >= 2:
                display_name = " ".join(w.capitalize() for w in filename_name.split())
                extracted_data["employee_name"] = display_name
                logger.info(
                    "Filename-derived name fallback: %r (file=%s)",
                    display_name, attachment.filename,
                )
                if employee_id is None:
                    employee_id = _fuzzy_match_employee(filename_name, employees)

        # Forwarded-from name fallback: use the original-sender name from the
        # forward block. Never overwrite the extracted name — it's only a
        # signal for matching known users.
        if employee_id is None and email_record.forwarded_from_name:
            employee_id = _fuzzy_match_employee(
                email_record.forwarded_from_name, employees
            )
            if employee_id is not None:
                logger.info(
                    "Resolved employee via forwarded-from name: %r",
                    email_record.forwarded_from_name,
                )

        # Body-email fallback: if the document carries an email address whose
        # exact value matches a known user's email, use that user.
        if employee_id is None:
            body_emails = extracted_data.get("contact_emails") or []
            if isinstance(body_emails, list):
                known_emails = {
                    (emp.get("email") or "").strip().lower(): emp["id"]
                    for emp in employees
                    if emp.get("email")
                }
                for candidate_email in body_emails:
                    normalized = str(candidate_email).strip().lower()
                    if normalized in known_emails:
                        employee_id = known_emails[normalized]
                        logger.info(
                            "Resolved employee via in-document email: %r",
                            normalized,
                        )
                        break

        # Chain-senders resolution: try every (name, email) pulled from the
        # forward chain against the known-user list. If exactly one chain
        # entry matches a real user (by exact email or fuzzy name), auto-
        # assign. Multiple matches on *different* users means we can't be
        # sure — leave employee_id None and surface the whole chain to
        # the reviewer so they pick. The unmatched chain is persisted onto
        # the IngestionTimesheet for the review UI regardless of whether
        # we also fell through to auto-create.
        chain_match_ids: set[int] = set()
        chain_from_email = email_record.chain_senders or []
        if employee_id is None and chain_from_email:
            known_emails_map = {
                (emp.get("email") or "").strip().lower(): emp["id"]
                for emp in employees
                if emp.get("email")
            }
            for entry in chain_from_email:
                entry_email = (entry.get("email") or "").strip().lower()
                if entry_email and entry_email in known_emails_map:
                    chain_match_ids.add(known_emails_map[entry_email])
                    continue
                entry_name = entry.get("name") or ""
                if entry_name:
                    matched = _fuzzy_match_employee(entry_name, employees)
                    if matched is not None:
                        chain_match_ids.add(matched)
            if len(chain_match_ids) == 1:
                employee_id = next(iter(chain_match_ids))
                logger.info(
                    "Resolved employee via forward chain (unique match): user_id=%s",
                    employee_id,
                )

        # ── Client resolution ──────────────────────────────────────────────
        # Optimized for the staffing-firm tenant model: the firm (e.g. Acuent)
        # places consultants at clients (e.g. DXC), and the consultant's work
        # email domain identifies which client they're embedded at. Project
        # codes inside the document (e.g. "wmACoE-Aegon-L3-Revitalize") are
        # downstream-customer / program metadata, not client identity, so the
        # LLM-extracted client_name is the last-resort signal. See
        # _resolve_client_id for the full precedence.
        employee_default_client_id: int | None = None
        if employee_id is not None:
            for emp in employees:
                if emp["id"] == employee_id and emp.get("default_client_id"):
                    employee_default_client_id = emp["default_client_id"]
                    break

        body_emails_raw = extracted_data.get("contact_emails") or []
        body_emails_list = (
            [str(e) for e in body_emails_raw if e]
            if isinstance(body_emails_raw, list) else []
        )

        client_id = _resolve_client_id(
            employee_default_client_id=employee_default_client_id,
            forwarded_from_email=email_record.forwarded_from_email,
            body_emails=body_emails_list,
            sender_email=email_record.sender_email,
            extracted_client_name=(
                extracted_data.get("client_name") or extracted_data.get("client") or ""
            ),
            clients=clients,
        )

        # Normalize line items
        line_items_data = _normalize_line_items(
            line_items=extracted_data.get("line_items", []),
            period_start=extracted_data.get("period_start"),
            period_end=extracted_data.get("period_end"),
        )

        # DB entity resolution + project_id per line item
        employee_id, client_id, line_items_data = await _resolve_db_entities(
            extracted_data=extracted_data,
            line_items_data=line_items_data,
            employee_id=employee_id,
            client_id=client_id,
            tenant_id=tenant_id,
            session=session,
        )

        # Prefer the forwarded-from sender when we have one — the outer sender
        # on a forwarded email is the forwarder, not the timesheet owner.
        effective_sender_email = (
            email_record.forwarded_from_email or email_record.sender_email
        )
        effective_sender_name = (
            email_record.forwarded_from_name or email_record.sender_name
        )

        # If the forward chain carries candidates the reviewer should choose
        # between (zero matches, or multiple matches on different users),
        # hold off on both auto-create paths and let the reviewer pick.
        # Creating a placeholder user now would saddle the record with the
        # outer mailbox's email instead of the actual submitter's address.
        needs_reviewer_chain_choice = bool(chain_from_email) and employee_id is None

        # Auto-create an employee user from extracted name if no match exists.
        if employee_id is None and not needs_reviewer_chain_choice:
            employee_id = await _resolve_or_create_extracted_employee_user(
                extracted_employee_name=extracted_data.get("employee_name"),
                sender_email=effective_sender_email,
                tenant_id=tenant_id,
                session=session,
            )

        # External user fallback — only when we have a real sender email address
        if (
            employee_id is None
            and not needs_reviewer_chain_choice
            and effective_sender_email
            and effective_sender_email != "unknown@unknown.com"
            and "@" in effective_sender_email
        ):
            employee_id = await _resolve_or_create_external_user(
                sender_email=effective_sender_email,
                sender_name=effective_sender_name,
                extracted_employee_name=extracted_data.get("employee_name"),
                tenant_id=tenant_id,
                session=session,
            )

        # Build the match-suggestions payload the reviewer UI consumes. Only
        # included when there's at least one chain entry AND the system
        # wasn't able to auto-assign a unique employee from it.
        llm_match_suggestions: dict | None = None
        if chain_from_email and len(chain_match_ids) != 1:
            suggestions = []
            extracted_name_norm = (extracted_data.get("employee_name") or "").strip().lower()
            for entry in chain_from_email:
                entry_email = (entry.get("email") or "").strip().lower() or None
                entry_name = (entry.get("name") or "").strip() or None
                existing_user_id: int | None = None
                if entry_email:
                    for emp in employees:
                        if (emp.get("email") or "").strip().lower() == entry_email:
                            existing_user_id = emp["id"]
                            break
                if existing_user_id is None and entry_name:
                    existing_user_id = _fuzzy_match_employee(entry_name, employees)
                suggestions.append({
                    "name": entry_name,
                    "email": entry_email,
                    "existing_user_id": existing_user_id,
                    "matches_extracted_name": (
                        bool(entry_name)
                        and bool(extracted_name_norm)
                        and entry_name.lower() == extracted_name_norm
                    ),
                })
            llm_match_suggestions = {"chain_candidates": suggestions}

        # Anomaly detection
        anomalies = await detect_anomalies(
            extracted_data=extracted_data,
            line_items=line_items_data,
            employee_name=extracted_data.get("employee_name"),
            period_start=extracted_data.get("period_start"),
            period_end=extracted_data.get("period_end"),
        )

        # Create IngestionTimesheet record
        timesheet = IngestionTimesheet(
            tenant_id=tenant_id,
            email_id=email_record.id,
            attachment_id=attachment_record.id,
            employee_id=employee_id,
            client_id=client_id,
            period_start=_parse_iso_date(extracted_data.get("period_start")),
            period_end=_parse_iso_date(extracted_data.get("period_end")),
            total_hours=_resolve_total_hours(extracted_data, line_items_data),
            status=IngestionTimesheetStatus.pending,
            extracted_data=extracted_data,
            extracted_supervisor_name=(extracted_data.get("supervisor_name") or "").strip() or None,
            llm_anomalies=anomalies,
            llm_match_suggestions=llm_match_suggestions,
            submitted_at=email_record.received_at,
            created_at=now,
            updated_at=now,
        )
        session.add(timesheet)
        await session.flush()

        # Create line items
        for item in line_items_data:
            work_date = _parse_iso_date(item.get("work_date"))
            hours = _to_decimal(item.get("hours"))
            if work_date is None or hours is None:
                continue
            line_item = IngestionTimesheetLineItem(
                ingestion_timesheet_id=timesheet.id,
                work_date=work_date,
                hours=hours,
                description=item.get("description"),
                project_code=item.get("project_code"),
                project_id=item.get("project_id"),
            )
            session.add(line_item)

        # Audit log
        audit = IngestionAuditLog(
            ingestion_timesheet_id=timesheet.id,
            user_id=None,
            action="auto_ingested",
            actor_type=IngestionAuditActorType.system,
            new_value={
                "extraction_method": extraction.method,
                "extraction_confidence": extraction.confidence,
                "employee_id": employee_id,
                "client_id": client_id,
                "line_items_count": len(line_items_data),
                "period": f"{extracted_data.get('period_start')} to {extracted_data.get('period_end')}",
            },
            created_at=now,
        )
        session.add(audit)
        created_count += 1

    return created_count


async def _load_known_employees(session: AsyncSession, tenant_id: int) -> list[dict]:
    result = await session.execute(
        select(User.id, User.full_name, User.email, User.default_client_id).where(
            User.tenant_id == tenant_id
        )
    )
    return [
        {
            "id": row.id,
            "full_name": row.full_name,
            "email": row.email or "",
            "default_client_id": row.default_client_id,
        }
        for row in result
    ]


async def _load_known_clients(session: AsyncSession, tenant_id: int) -> list[dict]:
    result = await session.execute(
        select(Client.id, Client.name, Client.contact_email).where(
            Client.tenant_id == tenant_id
        )
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "contact_email": (row.contact_email or "").strip().lower(),
        }
        for row in result
    ]


def _domain_of(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    return email.split("@", 1)[1].strip().lower()


def _resolve_client_id(
    *,
    employee_default_client_id: int | None,
    forwarded_from_email: str | None,
    body_emails: list[str] | None,
    sender_email: str | None,
    extracted_client_name: str | None,
    clients: list[dict],
) -> int | None:
    """
    Apply the staffing-firm client precedence:
      1. The employee's pinned default client.
      2. Forwarded-from sender domain (real submitter on a forwarded email).
      3. Any email domain mentioned in the document body.
      4. Outer sender domain (direct submissions with no forward chain).
      5. LLM-extracted client name fuzzy-matched to existing clients.
    Returns None if nothing matches; the reviewer picks in the UI.

    Pure function — no DB access, no I/O. Domain → client lookup is delegated
    to the existing _client_id_for_domain helper which already handles the
    "multiple clients share a domain" tie-break.
    """
    if employee_default_client_id is not None:
        return employee_default_client_id

    if forwarded_from_email:
        match = _client_id_for_domain(_domain_of(forwarded_from_email), clients)
        if match is not None:
            return match

    for candidate in body_emails or []:
        match = _client_id_for_domain(_domain_of(str(candidate)), clients)
        if match is not None:
            return match

    if sender_email:
        match = _client_id_for_domain(_domain_of(sender_email), clients)
        if match is not None:
            return match

    return _find_existing_client_id(extracted_client_name, clients)


def _client_id_for_domain(domain: str, clients: list[dict]) -> int | None:
    """Look up a client whose contact_email domain matches. If multiple clients
    share the same domain (e.g. two Toyota entities), return the one with the
    smallest id as the deterministic 'default' — reviewer overrides if wrong."""
    if not domain:
        return None
    matches = [c for c in clients if _domain_of(c.get("contact_email")) == domain]
    if not matches:
        return None
    matches.sort(key=lambda c: c["id"])
    return matches[0]["id"]


def _extract_emails_from_text(text: str | None) -> list[str]:
    """Pull email-shaped tokens from arbitrary text (signatures, document body)."""
    if not text:
        return []
    matches = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    # Preserve order, de-dupe, lowercase.
    seen: set[str] = set()
    out: list[str] = []
    for m in matches:
        lower = m.lower()
        if lower not in seen:
            seen.add(lower)
            out.append(lower)
    return out


def _find_existing_client_id(
    extracted_client_name: str | None,
    clients: list[dict],
) -> int | None:
    """Exact/fuzzy match the extracted client name against existing clients.
    Returns id if a strong match, else None. Does NOT create anything."""
    import difflib

    if not extracted_client_name:
        return None
    normalized = extracted_client_name.strip().lower()
    if not normalized:
        return None

    best_id: int | None = None
    best_ratio = 0.0
    for client in clients:
        existing = (client.get("name") or "").strip().lower()
        if not existing:
            continue
        if existing == normalized:
            return client["id"]
        ratio = difflib.SequenceMatcher(None, normalized, existing).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_id = client["id"]
    return best_id if best_ratio >= 0.85 else None


def _fuzzy_match_employee(
    extracted_name: str | None,
    known_employees: list[dict],
) -> int | None:
    """
    Deterministic fuzzy match of extracted employee name against known employees.
    Returns employee ID if a strong match is found (ratio >= 0.85), else None.
    This runs before the LLM to avoid hallucinated matches.
    """
    import difflib

    if not extracted_name:
        return None

    normalized = _normalize_person_name(extracted_name)
    if not normalized:
        return None

    best_id = None
    best_ratio = 0.0

    for emp in known_employees:
        emp_normalized = _normalize_person_name(emp.get("full_name"))
        if not emp_normalized:
            continue

        # Exact match
        if normalized == emp_normalized:
            return emp["id"]

        # Fuzzy ratio
        ratio = difflib.SequenceMatcher(None, normalized, emp_normalized).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_id = emp["id"]

    # Only accept high-confidence fuzzy matches
    if best_ratio >= 0.85:
        return best_id

    return None


def _normalize_person_name(value: str | None) -> str:
    if not value:
        return ""
    cleaned = " ".join(str(value).strip().split())
    return cleaned.lower().strip()


_FILENAME_NAME_STOPWORDS = {
    "timesheet", "timesheets", "time", "sheet", "sheets",
    "weekly", "week", "monthly", "month", "biweekly",
    "report", "hours", "log", "submission", "submitted",
    "final", "draft", "copy", "updated", "revised",
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "january", "february", "march", "april", "june",
    "july", "august", "september", "october", "november", "december",
    "mon", "tue", "tues", "wed", "thu", "thurs", "fri", "sat", "sun",
    "invoice", "consulting", "staffing", "for", "of", "from", "to",
}


def _derive_name_from_filename(filename: str | None) -> str:
    """
    Extract a best-guess person name from a timesheet filename.
    Example: 'Sridhar_Timesheet_March_2026.pdf' -> 'sridhar'
             'John Doe - Week 14.xlsx'           -> 'john doe'
    Returns an already-normalized (lowercased, trimmed) string, or ''.
    """
    if not filename:
        return ""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    # Split on common separators
    raw_tokens = re.split(r"[\s_\-.,()\[\]]+", stem)
    kept: list[str] = []
    for tok in raw_tokens:
        if not tok:
            continue
        lowered = tok.lower()
        if lowered in _FILENAME_NAME_STOPWORDS:
            continue
        # Skip pure digits (years, week numbers) and alnum date-ish tokens
        if not re.search(r"[A-Za-z]", tok):
            continue
        if re.fullmatch(r"\d{1,4}[A-Za-z]{1,4}\d{0,4}", tok):
            continue
        # Keep alphabetic-ish tokens
        kept.append(lowered)
        if len(kept) >= 3:
            break
    return " ".join(kept).strip()


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _resolve_total_hours(extracted_data: dict, line_items_data: list[dict]) -> Decimal | None:
    if line_items_data:
        total = Decimal("0")
        for item in line_items_data:
            hours = _to_decimal(item.get("hours"))
            if hours is not None:
                total += hours
        return total
    return _to_decimal(extracted_data.get("total_hours"))


async def _resolve_db_entities(
    extracted_data: dict,
    line_items_data: list[dict],
    employee_id: int | None,
    client_id: int | None,
    tenant_id: int,
    session: AsyncSession,
) -> tuple[int | None, int | None, list[dict]]:
    """
    Fill in employee_id, client_id, and per-line-item project_id from DB records
    when sender mapping and LLM suggestions didn't produce a match.

    Returns (employee_id, client_id, resolved_line_items).
    """
    from sqlalchemy import func as sa_func

    # ── Employee: DB name match ───────────────────────────────────────────
    if employee_id is None:
        extracted_name = _normalize_person_name(extracted_data.get("employee_name"))
        if extracted_name:
            # Exact full_name match
            res = await session.execute(
                select(User).where(
                    (User.tenant_id == tenant_id)
                    & (sa_func.lower(User.full_name) == extracted_name.lower())
                    & (User.is_active == True)
                )
            )
            user = res.scalar_one_or_none()

            # Fuzzy: each word of the extracted name as a substring
            if user is None:
                for part in extracted_name.lower().split():
                    if len(part) <= 2:
                        continue
                    res = await session.execute(
                        select(User).where(
                            (User.tenant_id == tenant_id)
                            & (sa_func.lower(User.full_name).contains(part))
                            & (User.is_active == True)
                        )
                    )
                    matches = res.scalars().all()
                    if len(matches) == 1:
                        user = matches[0]
                        break

            if user is not None:
                employee_id = user.id

    # ── Client: DB name match ─────────────────────────────────────────────
    if client_id is None:
        extracted_client = (
            extracted_data.get("client_name") or extracted_data.get("client") or ""
        ).strip()
        if extracted_client:
            # Exact name match
            res = await session.execute(
                select(Client).where(
                    (Client.tenant_id == tenant_id)
                    & (sa_func.lower(Client.name) == extracted_client.lower())
                )
            )
            client = res.scalar_one_or_none()

            # Partial name match
            if client is None:
                res = await session.execute(
                    select(Client).where(
                        (Client.tenant_id == tenant_id)
                        & (sa_func.lower(Client.name).contains(extracted_client.lower()))
                    )
                )
                matches = res.scalars().all()
                if len(matches) == 1:
                    client = matches[0]

            if client is not None:
                client_id = client.id

    # ── Project: resolve project_id per line item ─────────────────────────
    resolved_items: list[dict] = []
    for item in line_items_data:
        project_id = item.get("project_id")  # may already be set
        if project_id is None:
            project_code = (item.get("project_code") or "").strip()
            if project_code:
                # Exact code match
                res = await session.execute(
                    select(Project).where(
                        (Project.tenant_id == tenant_id)
                        & (sa_func.lower(Project.code) == project_code.lower())
                        & (Project.is_active == True)
                    )
                )
                project = res.scalar_one_or_none()

                # Name contains fallback
                if project is None:
                    res = await session.execute(
                        select(Project).where(
                            (Project.tenant_id == tenant_id)
                            & (sa_func.lower(Project.name).contains(project_code.lower()))
                            & (Project.is_active == True)
                        )
                    )
                    projects = res.scalars().all()
                    if len(projects) == 1:
                        project = projects[0]

                if project is not None:
                    project_id = project.id

        resolved_items.append({**item, "project_id": project_id})

    return employee_id, client_id, resolved_items


async def _resolve_or_create_external_user(
    sender_email: str,
    sender_name: str | None,
    extracted_employee_name: str | None,
    tenant_id: int,
    session: AsyncSession,
) -> int | None:
    from app.core.security import get_password_hash

    normalized_sender_name = _normalize_person_name(sender_name)
    normalized_extracted_name = _normalize_person_name(extracted_employee_name)

    if normalized_extracted_name and normalized_sender_name and normalized_extracted_name != normalized_sender_name:
        return None

    # If we have an extracted name, check if there's already a user with that
    # email whose name matches. If the names don't match, this email belongs
    # to a different person (e.g., shared sender email for multiple employees).
    result = await session.execute(
        select(User).where(
            (User.tenant_id == tenant_id) & (User.email == sender_email)
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        if normalized_extracted_name:
            existing_name = _normalize_person_name(existing.full_name)
            if existing_name and existing_name != normalized_extracted_name:
                # Name mismatch — this is a different person sent from the same email.
                # Don't match to this user. Fall through to create a new user instead.
                pass
            else:
                return existing.id
        else:
            # No extracted name and email matches an existing user. In a
            # shared-sender setup (e.g. ap@webilent.com sending everyone's
            # timesheets), silently assigning to the email owner is wrong —
            # we'd attribute other people's work to them. Leave unassigned so
            # a reviewer manually picks the right employee.
            return None

    base_username = sender_email.split("@", 1)[0].lower().replace(".", "_")
    username = base_username
    suffix = 1
    while True:
        taken = await session.execute(select(User).where(User.username == username))
        if taken.scalar_one_or_none() is None:
            break
        username = f"{base_username}_{suffix}"
        suffix += 1

    full_name = (
        (extracted_employee_name or "").strip()
        or (sender_name or "").strip()
        or base_username.replace("_", " ").title()
        or sender_email
    )
    user = User(
        tenant_id=tenant_id,
        email=sender_email,
        username=username,
        full_name=full_name,
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        is_active=True,
        has_changed_password=False,
        can_review=False,
        is_external=True,
    )
    session.add(user)
    await session.flush()
    return user.id


def _slugify_identity(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return slug or "employee"


async def _resolve_or_create_extracted_employee_user(
    extracted_employee_name: str | None,
    sender_email: str | None,
    tenant_id: int,
    session: AsyncSession,
) -> int | None:
    from app.core.security import get_password_hash

    normalized_extracted_name = _normalize_person_name(extracted_employee_name)
    display_name = " ".join(word.capitalize() for word in _normalize_person_name(extracted_employee_name).split())
    if not normalized_extracted_name or not display_name:
        return None

    # First, try to match by name against existing users
    existing_users_result = await session.execute(
        select(User).where(
            (User.tenant_id == tenant_id)
            & (User.is_active == True)
        )
    )
    for existing in existing_users_result.scalars().all():
        if _normalize_person_name(existing.full_name) == normalized_extracted_name:
            return existing.id

    # Use sender email for the new user account, but do NOT match to an existing
    # user by email alone — that would mis-assign timesheets when multiple employees'
    # timesheets are sent from the same email address.
    real_email = sender_email if sender_email and sender_email != "unknown@unknown.com" else None

    # No name match found — create a new user with the sender's real email if available
    use_email = real_email
    base_slug = _slugify_identity(display_name)

    if use_email:
        # Check if the real email is already taken by another user (different tenant, etc.)
        email_taken = await session.execute(
            select(User.id).where(User.email == use_email)
        )
        if email_taken.scalar_one_or_none() is not None:
            use_email = None  # Fall back to generated email

    if not use_email:
        # Generate a placeholder email as fallback
        suffix = 0
        while True:
            suffix_part = "" if suffix == 0 else f"_{suffix}"
            use_email = f"{base_slug}.{tenant_id}{suffix_part}@ingestion.internal"
            taken_result = await session.execute(
                select(User.id).where(User.email == use_email)
            )
            if taken_result.scalar_one_or_none() is None:
                break
            suffix += 1

    # Generate a unique username
    suffix = 0
    while True:
        suffix_part = "" if suffix == 0 else f"_{suffix}"
        candidate_username = f"{base_slug}_{tenant_id}{suffix_part}"
        taken_result = await session.execute(
            select(User.id).where(User.username == candidate_username)
        )
        if taken_result.scalar_one_or_none() is None:
            break
        suffix += 1

    # Insert with retry — two concurrent jobs can both pass the uniqueness
    # checks above, then both try to INSERT with the same email/username. The
    # losing insert raises IntegrityError. On conflict we:
    #   1. Roll the savepoint back
    #   2. Re-check if another worker just created the user we wanted (name match)
    #   3. Otherwise generate a fresh placeholder email/username and retry.
    hashed_password = get_password_hash("password")
    for attempt in range(3):
        try:
            async with session.begin_nested():
                created_user = User(
                    tenant_id=tenant_id,
                    email=use_email,
                    username=candidate_username,
                    full_name=display_name,
                    hashed_password=hashed_password,
                    role=UserRole.EMPLOYEE,
                    is_active=True,
                    has_changed_password=False,
                    can_review=False,
                    is_external=True,
                    ingestion_created_by="extracted_employee_name",
                )
                session.add(created_user)
                await session.flush()
            return created_user.id
        except IntegrityError:
            # Another worker won the race. Either:
            #   (a) they created the same person — find them by name and use that id
            #   (b) the collision is on email/username only — generate fresh ones and retry
            recheck = await session.execute(
                select(User).where(
                    (User.tenant_id == tenant_id)
                    & (User.is_active == True)
                )
            )
            for existing in recheck.scalars().all():
                if _normalize_person_name(existing.full_name) == normalized_extracted_name:
                    return existing.id
            # Not the same person — force a fresh synthetic email/username and retry.
            suffix = attempt + 1
            use_email = f"{base_slug}.{tenant_id}_{suffix}_{int(datetime.now(timezone.utc).timestamp())}@ingestion.internal"
            candidate_username = f"{base_slug}_{tenant_id}_{suffix}_{int(datetime.now(timezone.utc).timestamp())}"
    # Gave up after retries.
    logger.warning(
        "Failed to create extracted-employee user after retries: name=%s tenant=%s",
        display_name, tenant_id,
    )
    return None
