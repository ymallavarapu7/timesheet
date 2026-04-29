"""Fleet runner: run alembic upgrade head against every active tenant
database (Phase 3.E).

Composes the same alembic-upgrade step that ``provision_tenant_db.py``
uses, but for every active tenant in the control plane. Each tenant
gets a ``TenantProvisioningJob`` row of kind ``migrate`` recording the
attempt, the resulting alembic revision, and any error.

Concurrency: tenants are migrated sequentially by default. A migration
that fails on one tenant does not stop the others; the runner finishes
and reports ``failed=N`` so an operator can decide whether to retry or
roll back.

Usage::

    docker exec timesheet-api-1 sh -c "cd /app && PYTHONPATH=/app python scripts/migrate_all_tenants.py"

Flags:
    --dry-run       List tenants that would be migrated and exit.
    --slug <slug>   Migrate only the named slug (repeatable).
    --include-pending  Include tenants without ``db_name`` set
                       (provisioning never completed). Default: skip.

Exit codes:
    0  - every targeted tenant migrated cleanly
    1  - one or more tenants failed (stderr lists which)
    2  - usage error / control plane unreachable
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.models.control import ControlTenant, TenantProvisioningJob
from app.models.control.tenant import ControlTenantStatus
from app.models.control.tenant_provisioning_job import (
    ProvisioningJobKind,
    ProvisioningJobStatus,
)


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_all_tenants")


def _tenant_db_url(db_name: str) -> str:
    """Build the asyncpg URL for a tenant DB by swapping the database
    name in the shared connection URL. Mirrors ``provision_tenant_db``.
    """
    base = urlparse(settings.database_url)
    return f"{base.scheme}://{base.netloc}/{db_name}"


def _run_alembic_upgrade(db_url: str) -> str:
    """Shell out to ``alembic upgrade head`` against ``db_url``. Returns
    stdout+stderr concatenated for logging on failure. Raises
    RuntimeError on non-zero exit.
    """
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd="/app",
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade failed (exit {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return f"{result.stdout}\n{result.stderr}".strip()


async def _read_alembic_revision(db_url: str) -> str | None:
    engine = create_async_engine(db_url)
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
    finally:
        await engine.dispose()


async def _load_targets(
    session: AsyncSession,
    slugs: list[str] | None,
    include_pending: bool,
) -> list[ControlTenant]:
    stmt = select(ControlTenant).where(
        ControlTenant.status == ControlTenantStatus.active
    )
    if slugs:
        stmt = stmt.where(ControlTenant.slug.in_(slugs))
    rows = (await session.execute(stmt)).scalars().all()
    if not include_pending:
        rows = [t for t in rows if t.db_name]
    return list(rows)


async def _record_job(
    session: AsyncSession,
    tenant: ControlTenant,
) -> TenantProvisioningJob:
    job = TenantProvisioningJob(
        tenant_id=tenant.id,
        kind=ProvisioningJobKind.migrate,
        status=ProvisioningJobStatus.running,
        started_at=datetime.now(timezone.utc),
    )
    session.add(job)
    await session.flush()
    await session.commit()
    return job


async def _finish_job(
    session: AsyncSession,
    job: TenantProvisioningJob,
    *,
    revision: str | None,
    error: str | None,
) -> None:
    job.status = (
        ProvisioningJobStatus.failed if error else ProvisioningJobStatus.succeeded
    )
    job.completed_at = datetime.now(timezone.utc)
    job.alembic_revision = revision
    if error:
        # Truncate to keep the audit row a reasonable size; full details
        # live in the runner stdout.
        job.error_message = error[:4000]
    session.add(job)
    await session.commit()


async def _migrate_one(
    session: AsyncSession,
    tenant: ControlTenant,
) -> tuple[bool, str | None]:
    """Run one tenant. Returns (ok, error_message)."""
    db_url = _tenant_db_url(tenant.db_name)
    job = await _record_job(session, tenant)

    try:
        _run_alembic_upgrade(db_url)
    except Exception as exc:  # noqa: BLE001
        logger.error("FAIL slug=%s: %s", tenant.slug, exc)
        await _finish_job(session, job, revision=None, error=str(exc))
        return False, str(exc)

    revision: str | None = None
    try:
        revision = await _read_alembic_revision(db_url)
    except Exception as exc:  # noqa: BLE001
        # Upgrade succeeded but we couldn't read the version. Still a
        # success from the migration's point of view; surface the read
        # failure as a warning and leave revision NULL.
        logger.warning(
            "slug=%s: alembic upgrade ok, version read failed: %s",
            tenant.slug, exc,
        )

    await _finish_job(session, job, revision=revision, error=None)
    logger.info("OK   slug=%s revision=%s", tenant.slug, revision)
    return True, None


async def _run(
    slugs: list[str] | None,
    include_pending: bool,
    dry_run: bool,
) -> int:
    engine = create_async_engine(settings.control_database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            tenants = await _load_targets(session, slugs, include_pending)
            if not tenants:
                logger.info("no tenants matched (slugs=%s, include_pending=%s)",
                            slugs, include_pending)
                return 0

            logger.info("targets: %s", ", ".join(t.slug for t in tenants))
            if dry_run:
                logger.info("dry-run: would migrate %d tenants", len(tenants))
                return 0

            ok = 0
            failed: list[str] = []
            for tenant in tenants:
                success, _ = await _migrate_one(session, tenant)
                if success:
                    ok += 1
                else:
                    failed.append(tenant.slug)

            logger.info("done: ok=%d failed=%d", ok, len(failed))
            if failed:
                logger.error("failed slugs: %s", ", ".join(failed))
                return 1
            return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slug", action="append",
        help="limit to one slug; repeat to add more",
    )
    parser.add_argument(
        "--include-pending", action="store_true",
        help="include tenants without db_name set (default: skip)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print targets and exit without running alembic",
    )
    args = parser.parse_args()

    try:
        rc = asyncio.run(
            _run(args.slug, args.include_pending, args.dry_run)
        )
    except KeyboardInterrupt:
        logger.warning("interrupted")
        rc = 130
    except Exception as exc:  # noqa: BLE001
        logger.exception("control plane unreachable or fatal error")
        print(f"fatal: {exc}", file=sys.stderr)
        rc = 2

    raise SystemExit(rc)


if __name__ == "__main__":
    main()
