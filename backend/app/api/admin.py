"""Admin-only operational endpoints.

Currently exposes a single system-health endpoint that aggregates the
operational state of the services the admin dashboard renders.

This is intentionally a separate router from `dashboard` because these
checks are infra-level (DB ping, Redis ping, mailbox freshness) rather
than tenant analytics. Future operational endpoints (worker stats,
queue depth, OAuth refresh activity) will land here too.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_tenant_db, require_role
from app.models.mailbox import Mailbox
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


SystemHealthStatus = Literal["healthy", "attention", "loading"]


class SystemHealthCheck(BaseModel):
    """Per-service operational status surfaced on the admin dashboard.

    Mirrored shape on the frontend (`SystemHealthCardProps`). Stable key
    is included so the UI can pin per-service icons / ordering without
    matching by display label.
    """

    key: str = Field(description="Stable identifier, e.g. 'database', 'redis'")
    label: str = Field(description="Human-readable service name")
    status: SystemHealthStatus = Field(description="healthy | attention | loading")
    subtitle: str = Field(description="Freshness or detail line, e.g. 'Last query 2s ago'")


def _format_relative_age(target: datetime, now: datetime) -> str:
    """Compact relative age. We keep it server-side so every client
    renders the same wording without time-zone drift."""
    delta = now - target
    secs = int(delta.total_seconds())
    if secs < 0:
        # Clock skew or future timestamp — present as "just now" instead
        # of a confusing "-3s ago".
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


async def _check_database(db: AsyncSession) -> SystemHealthCheck:
    """Round-trip a SELECT 1 and time it. Anything reachable counts as
    healthy; an exception flips to attention."""
    started = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return SystemHealthCheck(
            key="database",
            label="Database",
            status="healthy",
            subtitle=f"Last query {elapsed_ms}ms",
        )
    except Exception as exc:  # noqa: BLE001 - we want to coalesce all failures
        logger.warning("system-health database check failed: %s", exc)
        return SystemHealthCheck(
            key="database",
            label="Database",
            status="attention",
            subtitle="Unreachable",
        )


async def _check_redis() -> SystemHealthCheck:
    """PING the configured Redis. We import the client lazily so a
    Redis-less local env can still serve the rest of the dashboard."""
    try:
        import redis.asyncio as aioredis  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - redis is in requirements.txt
        return SystemHealthCheck(
            key="redis",
            label="Redis",
            status="attention",
            subtitle="Client library unavailable",
        )

    client = aioredis.from_url(settings.redis_url)
    started = time.perf_counter()
    try:
        await asyncio.wait_for(client.ping(), timeout=2.0)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return SystemHealthCheck(
            key="redis",
            label="Redis",
            status="healthy",
            subtitle=f"Last ping {elapsed_ms}ms",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("system-health redis check failed: %s", exc)
        return SystemHealthCheck(
            key="redis",
            label="Redis",
            status="attention",
            subtitle="Ping failed",
        )
    finally:
        try:
            await client.aclose()
        except Exception:  # pragma: no cover - cleanup best effort
            pass


async def _check_email_ingestion(db: AsyncSession) -> SystemHealthCheck:
    """Latest mailbox fetch wins. If no mailbox is configured at all we
    surface that explicitly rather than as a failure — a tenant without
    ingestion enabled is a normal state, not a degraded one."""
    result = await db.execute(
        select(Mailbox.last_fetched_at)
        .where(Mailbox.is_active.is_(True))
        .order_by(Mailbox.last_fetched_at.desc().nullslast())
        .limit(1)
    )
    last_fetched = result.scalar_one_or_none()
    interval_minutes = settings.email_fetch_interval_minutes

    if last_fetched is None:
        # No mailbox or none has ever fetched.
        active_count_result = await db.execute(
            select(Mailbox.id).where(Mailbox.is_active.is_(True)).limit(1)
        )
        has_active = active_count_result.first() is not None
        return SystemHealthCheck(
            key="email_ingestion",
            label="Email Ingestion",
            status="attention" if has_active else "healthy",
            subtitle=(
                "No mailbox has fetched yet"
                if has_active
                else "No active mailboxes"
            ),
        )

    now = datetime.now(timezone.utc)
    # Mailbox.last_fetched_at is timezone-aware on Postgres; defensive
    # in case a SQLite shim hands us a naive value.
    if last_fetched.tzinfo is None:
        last_fetched = last_fetched.replace(tzinfo=timezone.utc)
    age_seconds = (now - last_fetched).total_seconds()

    # Attention threshold: 2x the configured fetch interval. A single
    # missed cycle is normal (workers retry); two missed in a row means
    # something is genuinely stuck.
    threshold_seconds = max(60, interval_minutes * 60 * 2)
    status: SystemHealthStatus = "attention" if age_seconds > threshold_seconds else "healthy"
    relative = _format_relative_age(last_fetched, now)
    subtitle = (
        f"Last fetch {relative} · expected every {interval_minutes}m"
        if status == "attention"
        else f"Last fetch {relative}"
    )
    return SystemHealthCheck(
        key="email_ingestion",
        label="Email Ingestion",
        status=status,
        subtitle=subtitle,
    )


@router.get("/system-health", response_model=list[SystemHealthCheck])
async def get_system_health(
    db: AsyncSession = Depends(get_tenant_db),
    _: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> list[SystemHealthCheck]:
    """Aggregate operational status for the admin dashboard.

    Each check is independent and isolated: a failure in one (e.g. Redis
    down) does not mask the result of another. Each catches its own
    exceptions and returns a sentinel ``attention`` payload, so the
    response shape stays stable.

    The two DB-bound checks share a single session, so they run
    sequentially (AsyncSession does not support concurrent operations
    on the same session). Redis, which is independent of the session,
    runs concurrently with them.
    """
    redis_task = asyncio.create_task(_check_redis())
    database = await _check_database(db)
    email_ingestion = await _check_email_ingestion(db)
    redis_check = await redis_task
    return [database, redis_check, email_ingestion]
