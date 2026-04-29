"""Provision a dedicated database for a tenant (Phase 3.C.1).

Idempotent. Creates the database if missing, runs ``alembic upgrade
head`` against it, and writes the connection details onto the
control-plane ``tenants`` row. Does NOT flip ``is_isolated`` — that
happens after the data migration is verified.

Usage::

    docker exec timesheet-api-1 sh -c "cd /app && PYTHONPATH=/app python scripts/provision_tenant_db.py <slug>"

Steps:
    1. Look up the tenant in acufy_control by slug.
    2. Create database ``acufy_tenant_<slug>`` if it doesn't exist.
    3. Run alembic against the new database.
    4. Update the control-plane row with connection details.
    5. Record a TenantProvisioningJob row.

Safe to re-run: each step checks state first. A half-provisioned
tenant from a crashed prior run gets picked up where it left off.

Exit codes:
    0  - provisioning succeeded (or was already complete)
    1  - any failure (tenant not found, DB creation failed, alembic
         upgrade failed, etc.)
"""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.models.control import (
    ControlTenant,
    TenantProvisioningJob,
)
from app.models.control.tenant_provisioning_job import (
    ProvisioningJobKind,
    ProvisioningJobStatus,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("provision_tenant_db")


# Slug rules: lowercase alphanumeric + hyphens, 1-63 chars, no leading
# or trailing hyphen. Mirrors Postgres database name constraints
# (which allow more, but we keep the slug strict for simplicity).
_SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def _validate_slug(slug: str) -> None:
    if not _SLUG_PATTERN.match(slug):
        raise SystemExit(
            f"Invalid slug {slug!r}: must be lowercase alphanumeric + hyphens, "
            "1-63 chars, no leading/trailing hyphen."
        )


def _tenant_db_name(slug: str) -> str:
    """Postgres database name follows the slug. Hyphens stay legal in
    Postgres database identifiers; no transformation needed."""
    return f"acufy_tenant_{slug}"


def _tenant_db_url(db_name: str) -> str:
    """Build the asyncpg URL for a tenant DB by swapping the database
    name in the shared connection URL. We share host, port, user, and
    password with the existing tenant DB; production can move tenants
    to dedicated clusters by editing the control-plane row directly.
    """
    base = urlparse(settings.database_url)
    # ``ParseResult`` is immutable; rebuild the URL with the new path.
    return f"{base.scheme}://{base.netloc}/{db_name}"


async def _ensure_database_exists(db_name: str) -> bool:
    """Create the database if missing. Returns True if newly created."""
    # Connect to the postgres maintenance database, not the target
    # one (you can't `CREATE DATABASE` while inside the target).
    base = urlparse(settings.database_url)
    maint_url = f"{base.scheme}://{base.netloc}/postgres"
    engine = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = (await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": db_name},
            )).first() is not None
            if exists:
                logger.info("database %s already exists, skipping create", db_name)
                return False
            # Database name comes from a validated slug; safe to inline.
            await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
            logger.info("created database %s", db_name)
            return True
    finally:
        await engine.dispose()


def _run_alembic_upgrade(db_url: str) -> None:
    """Run ``alembic upgrade head`` against the target URL.

    We invoke alembic as a subprocess so the existing ``alembic/env.py``
    drives the migration loop without us having to re-implement the
    migration runner. The TENANT_DB_URL env var is read by env.py to
    override the default; that override is not yet wired (env.py uses
    settings.database_url today). For 3.C.1 we shell-override by
    setting DATABASE_URL just for this subprocess.
    """
    import os
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
        logger.error("alembic upgrade failed:\n%s\n%s", result.stdout, result.stderr)
        raise RuntimeError(f"alembic upgrade failed (exit {result.returncode})")
    logger.info("alembic upgrade head succeeded against %s", db_url)


async def _provision(slug: str) -> int:
    _validate_slug(slug)
    db_name = _tenant_db_name(slug)
    db_url = _tenant_db_url(db_name)

    base = urlparse(settings.database_url)
    db_host = base.hostname
    db_port = base.port or 5432

    control_engine = create_async_engine(settings.control_database_url)
    try:
        async with AsyncSession(control_engine, expire_on_commit=False) as session:
            tenant = (await session.execute(
                select(ControlTenant).where(ControlTenant.slug == slug)
            )).scalar_one_or_none()
            if tenant is None:
                logger.error("tenant slug=%s not found in acufy_control.tenants", slug)
                return 1

            job = TenantProvisioningJob(
                tenant_id=tenant.id,
                kind=ProvisioningJobKind.create,
                status=ProvisioningJobStatus.running,
                started_at=datetime.now(timezone.utc),
            )
            session.add(job)
            await session.flush()
            await session.commit()

            try:
                await _ensure_database_exists(db_name)
                _run_alembic_upgrade(db_url)

                # Persist connection details. We deliberately skip
                # encrypting credentials in 3.C.1 because all tenants
                # share the dev cluster's user/password; per-tenant
                # credentials are a follow-up. ``db_user_enc`` and
                # ``db_password_enc`` stay null until then.
                tenant.db_name = db_name
                tenant.db_host = db_host
                tenant.db_port = db_port
                session.add(tenant)

                # Mark the job complete.
                job.status = ProvisioningJobStatus.succeeded
                job.completed_at = datetime.now(timezone.utc)
                # Read the alembic revision after upgrade so we know
                # what schema this tenant is on.
                target_engine = create_async_engine(db_url)
                try:
                    async with target_engine.connect() as conn:
                        rev = (await conn.execute(
                            text("SELECT version_num FROM alembic_version")
                        )).scalar_one_or_none()
                        if rev is not None:
                            job.alembic_revision = rev
                finally:
                    await target_engine.dispose()
                session.add(job)
                await session.commit()
                logger.info("tenant %s provisioned (db=%s, alembic=%s)",
                            slug, db_name, job.alembic_revision)
                return 0
            except Exception as exc:  # noqa: BLE001
                # Mark the job failed but leave any partial work in
                # place so a re-run can pick up where we left off.
                job.status = ProvisioningJobStatus.failed
                job.error_message = str(exc)
                job.completed_at = datetime.now(timezone.utc)
                session.add(job)
                await session.commit()
                logger.exception("provisioning failed for slug=%s", slug)
                return 1
    finally:
        await control_engine.dispose()


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: provision_tenant_db.py <slug>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_provision(sys.argv[1])))


if __name__ == "__main__":
    main()
