"""
Email fetch and reprocess worker jobs.
Called by arq when a reviewer triggers email ingestion or reprocessing.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingested_email import IngestedEmail
from app.models.mailbox import Mailbox
from app.models.tenant import Tenant
from app.services.imap import fetch_messages, update_last_fetched_at
from app.services.ingestion_pipeline import process_email, reprocess_stored_email

logger = logging.getLogger(__name__)

JOB_STATUS_TTL_SECONDS = 86400


def _status_key(job_id: str) -> str:
    return f"ingestion:job-status:{job_id}"


def _build_summary(tenant_id: int, mode: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "mode": mode,
        "mailboxes_processed": 0,
        "mailboxes_failed": 0,
        "total_fetched": 0,
        "total_new": 0,
        "total_skipped": 0,
        "total_timesheets_created": 0,
        "skip_reasons": {},
        "message_diagnostics": [],
        "errors": [],
        "completed_at": None,
    }


async def _write_job_status(
    ctx: dict,
    *,
    job_id: str,
    tenant_id: int,
    mode: str,
    status: str,
    progress: int,
    message: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    redis = ctx.get("redis")
    if redis is None:
        logger.warning("Redis unavailable, cannot write job status for job_id=%s", job_id)
        return

    payload = {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "mode": mode,
        "status": status,
        "progress": progress,
        "message": message,
        "result": result,
        "error": error,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await redis.setex(
        _status_key(job_id),
        JOB_STATUS_TTL_SECONDS,
        json.dumps(payload, default=str),
    )


async def fetch_emails_for_tenant(
    ctx: dict,
    tenant_id: int,
    mode: str = "fetch",
    email_id: int | None = None,
    attachment_ids: list[int] | None = None,
    tenant_slug: str | None = None,
) -> dict:
    """arq job: fetch and process emails for a tenant (or reprocess).

    ``tenant_slug`` routes DB sessions to the tenant DB; resolved from the
    control plane when absent.
    """
    from app.db import AsyncSessionLocal
    from app.db_tenant import resolve_slug_for_tenant_id, tenant_session

    if tenant_slug is None:
        try:
            tenant_slug = await resolve_slug_for_tenant_id(tenant_id)
        except LookupError:
            tenant_slug = None

    def _open_session():
        # One callable that workers below can invoke per session-open.
        # When we have a slug we route through the registry; without
        # one we keep the legacy behaviour so manual / replay paths
        # still function.
        if tenant_slug:
            return tenant_session(tenant_slug)
        return AsyncSessionLocal()

    job_id = ctx.get("job_id") or f"fetch_tenant_{tenant_id}"
    summary = _build_summary(tenant_id, mode)
    await _write_job_status(
        ctx,
        job_id=job_id,
        tenant_id=tenant_id,
        mode=mode,
        status="in_progress",
        progress=5,
        message="Loading tenant ingestion context...",
    )

    # Validate tenant in a short session, then close before any IMAP work.
    async with _open_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        if not tenant:
            summary["errors"].append(f"Tenant {tenant_id} not found")
            summary["completed_at"] = datetime.now(timezone.utc).isoformat()
            await _write_job_status(
                ctx,
                job_id=job_id,
                tenant_id=tenant_id,
                mode=mode,
                status="failed",
                progress=100,
                message=f"Tenant {tenant_id} not found.",
                result=summary,
                error=summary["errors"][0],
            )
            return summary

        if not tenant.ingestion_enabled:
            summary["errors"].append(f"Tenant {tenant_id} does not have ingestion enabled")
            summary["completed_at"] = datetime.now(timezone.utc).isoformat()
            await _write_job_status(
                ctx,
                job_id=job_id,
                tenant_id=tenant_id,
                mode=mode,
                status="failed",
                progress=100,
                message="Ingestion is not enabled for this tenant.",
                result=summary,
                error=summary["errors"][0],
            )
            return summary
    # Pre-fetch IMAP messages outside any session so asyncio.to_thread
    # never runs inside one.
    prefetched: list[tuple[Mailbox, list[dict]]] | None = None
    if mode == "fetch":
        prefetched = await _prefetch_mailbox_messages(
            ctx, tenant_id, job_id, summary, tenant_slug=tenant_slug
        )

    try:
        async with _open_session() as session:
            if mode == "fetch":
                await _run_fetch_job(
                    ctx, session, tenant_id, job_id, summary,
                    prefetched=prefetched,
                    tenant_slug=tenant_slug,
                )
            else:
                await _run_reprocess_job(
                    ctx,
                    session,
                    tenant_id,
                    job_id,
                    summary,
                    mode=mode,
                    email_id=email_id,
                    attachment_ids=attachment_ids or [],
                )
    except Exception as exc:
        logger.exception("Worker job failed for tenant %s", tenant_id)
        summary["errors"].append(str(exc))
        summary["completed_at"] = datetime.now(timezone.utc).isoformat()
        await _write_job_status(
            ctx,
            job_id=job_id,
            tenant_id=tenant_id,
            mode=mode,
            status="failed",
            progress=100,
            message=str(exc),
            result=summary,
            error=str(exc),
        )
        return summary

    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    await _write_job_status(
        ctx,
        job_id=job_id,
        tenant_id=tenant_id,
        mode=mode,
        status="complete",
        progress=100,
        message=(
            f"Done: {summary['total_fetched']} fetched, "
            f"{summary['total_timesheets_created']} staged, "
            f"{summary['total_skipped']} skipped."
        ),
        result=summary,
    )
    return summary


async def _prefetch_mailbox_messages(
    ctx: dict,
    tenant_id: int,
    job_id: str,
    summary: dict[str, Any],
    *,
    tenant_slug: str | None = None,
) -> list[tuple[Mailbox, list[dict]]]:
    """Load mailboxes and fetch raw messages; sessions close before IMAP work."""
    from app.db import AsyncSessionLocal
    from app.db_tenant import tenant_session

    def _open_session():
        return tenant_session(tenant_slug) if tenant_slug else AsyncSessionLocal()

    async with _open_session() as session:
        result = await session.execute(
            select(Mailbox).where(
                (Mailbox.tenant_id == tenant_id) & (Mailbox.is_active == True)
            )
        )
        mailboxes = list(result.scalars().all())

    if not mailboxes:
        return []

    mailbox_messages: list[tuple[Mailbox, list[dict]]] = []
    for index, mailbox in enumerate(mailboxes, start=1):
        progress = 10 + int(((index - 1) / max(len(mailboxes), 1)) * 35)
        await _write_job_status(
            ctx,
            job_id=job_id,
            tenant_id=tenant_id,
            mode="fetch",
            status="in_progress",
            progress=progress,
            message=f"Connecting to {mailbox.label}...",
        )
        try:
            async with _open_session() as fetch_session:
                messages = await fetch_messages(mailbox, fetch_session)
            mailbox_messages.append((mailbox, messages))
        except Exception as exc:
            logger.error("Failed to fetch messages from mailbox %s: %s", mailbox.id, exc)
            summary["mailboxes_failed"] += 1
            summary["errors"].append(f"Mailbox {mailbox.id} ({mailbox.label}): {exc}")
            mailbox_messages.append((mailbox, []))

    return mailbox_messages


async def _run_fetch_job(
    ctx: dict,
    session: AsyncSession,
    tenant_id: int,
    job_id: str,
    summary: dict[str, Any],
    prefetched: list[tuple[Mailbox, list[dict]]] | None = None,
    *,
    tenant_slug: str | None = None,
) -> None:
    if prefetched is None:
        return

    if not prefetched:
        await _write_job_status(
            ctx,
            job_id=job_id,
            tenant_id=tenant_id,
            mode="fetch",
            status="complete",
            progress=100,
            message="No active mailboxes configured.",
            result=summary,
        )
        return

    for index, (mailbox, messages) in enumerate(prefetched, start=1):
        mailbox_label = mailbox.label
        progress = 45 + int(((index - 1) / max(len(prefetched), 1)) * 45)
        await _write_job_status(
            ctx,
            job_id=job_id,
            tenant_id=tenant_id,
            mode="fetch",
            status="in_progress",
            progress=progress,
            message=f"Processing {mailbox_label}...",
        )
        mailbox_progress_start = 45 + int(((index - 1) / max(len(prefetched), 1)) * 45)
        mailbox_progress_range = int(45 / max(len(prefetched), 1))
        mailbox_result = await _process_mailbox(
            mailbox=mailbox,
            messages=messages,
            tenant_id=tenant_id,
            session=session,
            ctx=ctx,
            job_id=job_id,
            base_progress=mailbox_progress_start,
            progress_range=mailbox_progress_range,
            tenant_slug=tenant_slug,
        )
        if mailbox_result["success"]:
            summary["mailboxes_processed"] += 1
            summary["total_fetched"] += mailbox_result["fetched"]
            summary["total_new"] += mailbox_result["new"]
            summary["total_skipped"] += mailbox_result["skipped"]
            summary["total_timesheets_created"] += mailbox_result["timesheets_created"]
            for reason, count in mailbox_result["skip_reasons"].items():
                summary["skip_reasons"][reason] = summary["skip_reasons"].get(reason, 0) + count
            summary["message_diagnostics"].extend(mailbox_result["message_diagnostics"])
        else:
            summary["mailboxes_failed"] += 1
            summary["errors"].append(
                f"Mailbox {mailbox.id} ({mailbox_label}): {mailbox_result['error']}"
            )

        await _write_job_status(
            ctx,
            job_id=job_id,
            tenant_id=tenant_id,
            mode="fetch",
            status="in_progress",
            progress=min(90, progress + 10),
            message=(
                f"Processed {mailbox_label}: {mailbox_result['fetched']} fetched, "
                f"{mailbox_result['timesheets_created']} staged."
            ),
            result=summary,
        )


async def _run_reprocess_job(
    ctx: dict,
    session: AsyncSession,
    tenant_id: int,
    job_id: str,
    summary: dict[str, Any],
    *,
    mode: str,
    email_id: int | None,
    attachment_ids: list[int],
) -> None:
    query = select(IngestedEmail).where(IngestedEmail.tenant_id == tenant_id)
    if mode == "reprocess_skipped":
        query = query.where(
            (IngestedEmail.has_attachments == True)
            & (~IngestedEmail.ingestion_timesheets.any())
        )
    elif mode in ("reprocess_attachments", "reprocess_email"):
        if email_id is None:
            raise ValueError(f"email_id is required for mode '{mode}'")
        query = query.where(IngestedEmail.id == email_id)
    else:
        if email_id is not None:
            query = query.where(IngestedEmail.id == email_id)

    query = query.order_by(IngestedEmail.received_at.desc().nullslast(), IngestedEmail.id.desc())
    email_result = await session.execute(query)
    emails = list(email_result.scalars().all())

    if not emails:
        await _write_job_status(
            ctx,
            job_id=job_id,
            tenant_id=tenant_id,
            mode=mode,
            status="complete",
            progress=100,
            message="No stored emails matched this reprocess request.",
            result=summary,
        )
        return

    summary["total_fetched"] = len(emails)
    for index, email_record in enumerate(emails, start=1):
        progress = 10 + int((index / max(len(emails), 1)) * 80)
        await _write_job_status(
            ctx,
            job_id=job_id,
            tenant_id=tenant_id,
            mode=mode,
            status="in_progress",
            progress=progress,
            message=f"Reprocessing {email_record.subject or email_record.sender_email}...",
            result=summary,
        )
        pipeline_result = await reprocess_stored_email(
            email_id=email_record.id,
            tenant_id=tenant_id,
            session=session,
            attachment_ids=attachment_ids if mode == "reprocess_attachments" else None,
        )
        if pipeline_result.skipped:
            summary["total_skipped"] += 1
            reason = pipeline_result.skip_reason or "unknown"
            summary["skip_reasons"][reason] = summary["skip_reasons"].get(reason, 0) + 1
        else:
            summary["total_new"] += 1
            summary["total_timesheets_created"] += pipeline_result.timesheets_created

        summary["message_diagnostics"].append(
            {
                "email_id": pipeline_result.email_id,
                "message_id": pipeline_result.message_id,
                "subject": pipeline_result.subject,
                "sender_email": pipeline_result.sender_email,
                "skipped": pipeline_result.skipped,
                "skip_reason": pipeline_result.skip_reason,
                "skip_detail": pipeline_result.skip_detail,
                "timesheets_created": pipeline_result.timesheets_created,
                "errors": pipeline_result.errors,
            }
        )

        if pipeline_result.errors:
            summary["errors"].extend(pipeline_result.errors)


async def _process_mailbox(
    mailbox: Mailbox,
    messages: list[dict],
    tenant_id: int,
    session: AsyncSession,
    ctx: dict | None = None,
    job_id: str | None = None,
    base_progress: int = 10,
    progress_range: int = 70,
    *,
    tenant_slug: str | None = None,
) -> dict:
    """Process pre-fetched messages from one mailbox. Never raises."""
    mailbox_id = mailbox.id
    mailbox_label = mailbox.label
    result = {
        "success": False,
        "fetched": len(messages),
        "new": 0,
        "skipped": 0,
        "timesheets_created": 0,
        "skip_reasons": {},
        "message_diagnostics": [],
        "error": None,
    }

    try:
        if not messages:
            await update_last_fetched_at(mailbox, session)
            await session.commit()
            result["success"] = True
            return result

        # Up to 5 in parallel; each message gets its own DB session.
        import asyncio
        from app.db import AsyncSessionLocal
        from app.db_tenant import tenant_session

        def _open_msg_session():
            return tenant_session(tenant_slug) if tenant_slug else AsyncSessionLocal()

        total_messages = len(messages)
        CONCURRENCY = 5
        sem = asyncio.Semaphore(CONCURRENCY)
        diagnostics_lock = asyncio.Lock()

        async def _process_one(msg_index: int, raw_message: dict):
            async with sem:
                if ctx and job_id and total_messages > 0:
                    msg_progress = base_progress + int(((msg_index) / total_messages) * progress_range)
                    await _write_job_status(
                        ctx,
                        job_id=job_id,
                        tenant_id=tenant_id,
                        mode="fetch",
                        status="in_progress",
                        progress=msg_progress,
                        message=f"Processing email {msg_index + 1}/{total_messages} from {mailbox_label}...",
                    )

                try:
                    async with _open_msg_session() as msg_session:
                        pipeline_result = await process_email(
                            raw_message=raw_message,
                            mailbox_id=mailbox.id,
                            tenant_id=tenant_id,
                            session=msg_session,
                        )
                        await msg_session.commit()

                    async with diagnostics_lock:
                        if pipeline_result.skipped:
                            result["skipped"] += 1
                            reason = pipeline_result.skip_reason or "unknown"
                            result["skip_reasons"][reason] = result["skip_reasons"].get(reason, 0) + 1
                        else:
                            result["new"] += 1
                            result["timesheets_created"] += pipeline_result.timesheets_created

                        result["message_diagnostics"].append(
                            {
                                "email_id": pipeline_result.email_id,
                                "message_id": pipeline_result.message_id,
                                "subject": pipeline_result.subject,
                                "sender_email": pipeline_result.sender_email,
                                "skipped": pipeline_result.skipped,
                                "skip_reason": pipeline_result.skip_reason,
                                "skip_detail": pipeline_result.skip_detail,
                                "timesheets_created": pipeline_result.timesheets_created,
                                "errors": pipeline_result.errors,
                            }
                        )

                except Exception as exc:
                    logger.error(
                        "Failed to process message in mailbox %s: %s",
                        mailbox_id,
                        exc,
                    )
                    async with diagnostics_lock:
                        result["skipped"] += 1
                        result["message_diagnostics"].append(
                            {
                                "email_id": None,
                                "message_id": None,
                                "subject": None,
                                "sender_email": None,
                                "skipped": True,
                                "skip_reason": "message_processing_failed",
                                "skip_detail": str(exc),
                                "timesheets_created": 0,
                                "errors": [str(exc)],
                            }
                        )

        await asyncio.gather(*[
            _process_one(idx, msg) for idx, msg in enumerate(messages)
        ])

        await update_last_fetched_at(mailbox, session)
        await session.commit()
        result["success"] = True
    except Exception as exc:
        logger.error("Mailbox %s fetch failed: %s", mailbox_id, exc)
        try:
            await session.rollback()
        except Exception:
            logger.debug("Rollback after mailbox failure also failed", exc_info=True)
        result["error"] = str(exc)

    return result


async def enqueue_reprocess_skipped_fanout(
    tenant_id: int,
    email_ids: list[int],
    *,
    tenant_slug: str | None = None,
) -> str:
    """Enqueue one reprocess job per email so a slow attachment can't
    consume the whole 300s budget. Umbrella status is marked complete
    immediately; per-email jobs track their own progress."""
    from arq import create_pool
    from app.workers.settings import get_redis_settings

    redis = await create_pool(get_redis_settings())
    try:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        batch_id = f"reprocess_skipped_batch_tenant_{tenant_id}_{timestamp}"

        if not email_ids:
            await _write_job_status(
                {"redis": redis},
                job_id=batch_id,
                tenant_id=tenant_id,
                mode="reprocess_skipped",
                status="complete",
                progress=100,
                message="No skipped emails to reprocess.",
                result={"enqueued": 0},
            )
            return batch_id

        for email_id in email_ids:
            child_id = f"reprocess_email_tenant_{tenant_id}_{email_id}_{timestamp}"
            await _write_job_status(
                {"redis": redis},
                job_id=child_id,
                tenant_id=tenant_id,
                mode="reprocess_email",
                status="queued",
                progress=0,
                message=f"Reprocess job queued for email {email_id}.",
            )
            enqueue_kwargs = {"_job_id": child_id}
            if tenant_slug is not None:
                enqueue_kwargs["tenant_slug"] = tenant_slug
            await redis.enqueue_job(
                "fetch_emails_for_tenant",
                tenant_id,
                "reprocess_email",
                email_id,
                [],
                **enqueue_kwargs,
            )

        await _write_job_status(
            {"redis": redis},
            job_id=batch_id,
            tenant_id=tenant_id,
            mode="reprocess_skipped",
            status="complete",
            progress=100,
            message=(
                f"Dispatched {len(email_ids)} per-email reprocess jobs. "
                "Individual progress is tracked per child job; the skipped "
                "list will shrink as each completes."
            ),
            result={"enqueued": len(email_ids)},
        )
        return batch_id
    except Exception as exc:
        raise RuntimeError(f"Failed to enqueue reprocess-skipped fan-out: {exc}. Is Redis running?") from exc
    finally:
        await redis.close()


async def enqueue_fetch_job(
    tenant_id: int,
    *,
    mode: str = "fetch",
    email_id: int | None = None,
    attachment_ids: list[int] | None = None,
    tenant_slug: str | None = None,
) -> str:
    """Enqueue a fetch/reprocess job; ``tenant_slug`` lets the worker
    skip a control-plane lookup when known by the caller."""
    from arq import create_pool
    from arq.constants import (
        default_queue_name,
        in_progress_key_prefix,
        job_key_prefix,
        result_key_prefix,
        retry_key_prefix,
    )
    from arq.jobs import Job, JobStatus

    from app.workers.settings import get_redis_settings

    redis = await create_pool(get_redis_settings())
    try:
        if mode == "fetch":
            job_id = f"fetch_tenant_{tenant_id}"
            existing_job = Job(job_id, redis)
            existing_status = await existing_job.status()

            if existing_status in (JobStatus.deferred, JobStatus.queued, JobStatus.in_progress):
                return job_id

            if existing_status != JobStatus.not_found:
                await redis.delete(
                    job_key_prefix + job_id,
                    in_progress_key_prefix + job_id,
                    result_key_prefix + job_id,
                    retry_key_prefix + job_id,
                    _status_key(job_id),
                )
                await redis.zrem(default_queue_name, job_id)
        else:
            target_token = str(email_id or "all")
            timestamp = int(datetime.now(timezone.utc).timestamp())
            job_id = f"{mode}_tenant_{tenant_id}_{target_token}_{timestamp}"

        await _write_job_status(
            {"redis": redis},
            job_id=job_id,
            tenant_id=tenant_id,
            mode=mode,
            status="queued",
            progress=0,
            message=(
                "Fetch job queued for this tenant."
                if mode == "fetch"
                else "Reprocess job queued for this tenant."
            ),
        )

        enqueue_kwargs = {"_job_id": job_id}
        if tenant_slug is not None:
            enqueue_kwargs["tenant_slug"] = tenant_slug
        job = await redis.enqueue_job(
            "fetch_emails_for_tenant",
            tenant_id,
            mode,
            email_id,
            attachment_ids or [],
            **enqueue_kwargs,
        )
        if job is None:
            return job_id
        return job_id
    except Exception as exc:
        raise RuntimeError(f"Failed to enqueue fetch job: {exc}. Is Redis running?") from exc
    finally:
        await redis.close()


async def scheduled_fetch_emails(ctx: dict) -> None:
    """arq cron task: every 15 min, fan out fetch jobs over active tenants."""
    from app.workers.reminder_worker import _load_tenant_settings
    from app.db_control import AsyncControlSessionLocal
    from app.db_tenant import tenant_session
    from app.models.control import ControlTenant

    async with AsyncControlSessionLocal() as control_session:
        result = await control_session.execute(
            select(ControlTenant).where(ControlTenant.status == "active")
        )
        control_tenants = list(result.scalars().all())

    # Evaluate each tenant's fetch window in its own timezone.
    from app.core.timezone_utils import now_for_tenant

    for control_tenant in control_tenants:
        try:
            now = now_for_tenant(control_tenant.timezone)

            async with tenant_session(control_tenant.slug) as session:
                tenant_settings = await _load_tenant_settings(
                    control_tenant.id, session
                )

            if tenant_settings.get("fetch_emails_enabled") != "true":
                continue

            if not _should_fetch_now(tenant_settings, now):
                continue

            await enqueue_fetch_job(
                control_tenant.id, tenant_slug=control_tenant.slug
            )
            logger.info(
                "Auto-fetch enqueued for tenant %s (%s)",
                control_tenant.id, control_tenant.slug,
            )
        except Exception as exc:
            logger.error(
                "Auto-fetch enqueue failed for tenant %s (%s): %s",
                control_tenant.id, control_tenant.slug, exc,
            )


def _should_fetch_now(tenant_settings: dict, now: datetime) -> bool:
    """
    Returns True if the current time falls within a cron window
    that matches the tenant's fetch schedule.
    Defaults are read from app settings (configurable via .env).
    """
    from app.core.config import settings as app_settings

    interval = int(tenant_settings.get(
        "fetch_emails_interval_minutes",
        str(app_settings.email_fetch_interval_minutes),
    ))
    days_str = tenant_settings.get(
        "fetch_emails_days",
        app_settings.email_fetch_days,
    )
    start_time_str = tenant_settings.get(
        "fetch_emails_start_time",
        app_settings.email_fetch_start_time,
    )
    end_time_str = tenant_settings.get(
        "fetch_emails_end_time",
        app_settings.email_fetch_end_time,
    )

    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    allowed_days = [d.strip().lower() for d in days_str.split(",")]
    current_day = day_names[now.weekday()]
    if current_day not in allowed_days:
        return False

    current_minutes = now.hour * 60 + now.minute
    try:
        start_h, start_m = map(int, start_time_str.split(":"))
        end_h, end_m = map(int, end_time_str.split(":"))
    except (ValueError, AttributeError):
        return False
    start_total = start_h * 60 + start_m
    end_total = end_h * 60 + end_m
    if not (start_total <= current_minutes <= end_total):
        return False

    minutes_since_start = current_minutes - start_total
    if minutes_since_start < 0:
        return False
    # Cron window width: derive from the cron schedule so we don't miss a
    # tick.  Parse the configured minutes and use the smallest gap, capped
    # at 15 as a sensible floor.
    try:
        cron_mins = sorted(
            int(m.strip())
            for m in app_settings.worker_cron_minutes.split(",")
            if m.strip()
        )
        if len(cron_mins) >= 2:
            cron_window = min(cron_mins[i + 1] - cron_mins[i] for i in range(len(cron_mins) - 1))
        else:
            cron_window = 15
    except (ValueError, AttributeError):
        cron_window = 15
    return minutes_since_start % interval < cron_window


async def get_job_status(job_id: str) -> dict:
    """
    Poll the status of a job by job_id.
    """
    from arq import create_pool
    from arq.jobs import Job, JobStatus

    from app.workers.settings import get_redis_settings

    redis = await create_pool(get_redis_settings())
    try:
        stored_status = await redis.get(_status_key(job_id))
        if stored_status:
            payload = json.loads(stored_status)
            return payload

        job = Job(job_id, redis)
        status = await job.status()

        if status == JobStatus.complete:
            result = await job.result()
            return {"status": "complete", "job_id": job_id, "progress": 100, "message": "Done", "result": result}
        if status == JobStatus.in_progress:
            return {"status": "in_progress", "job_id": job_id, "progress": 50, "message": "Processing..."}
        if status in (JobStatus.deferred, JobStatus.queued):
            return {"status": "queued", "job_id": job_id, "progress": 0, "message": "Queued..."}
        return {"status": "not_found", "job_id": job_id, "progress": 0, "message": "Job not found."}
    except Exception as exc:
        raise RuntimeError(f"Failed to get job status: {exc}. Is Redis running?") from exc
    finally:
        await redis.close()
