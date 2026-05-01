"""One-shot cleanup of orphan supervisor "users" in tenant DBs.

Background:
    Migration 036 (since reverted by 037) had ``supervisor_user_id`` as
    an FK to ``users.id`` on ``ingestion_timesheets`` and
    ``time_entries``. Service-layer code from that era populated the
    column by auto-creating User rows from the LLM's
    ``supervisor_name`` extraction. The supervisor on a staffing-firm
    timesheet is typically a person at the *client*, not a tenant
    user — so those rows are pollution, not real users.

    The current ingestion pipeline does NOT create users from
    supervisor names; it only auto-creates from ``employee_name`` and
    forward-chain senders. So this script removes historical
    pollution; it does not need a follow-up to keep working.

What it does:
    For each provisioned tenant DB, finds users where:
        - ``is_external = True``
        - ``full_name`` matches a value in
          ``time_entries.supervisor_name`` OR
          ``ingestion_timesheets.extracted_supervisor_name`` for the
          same tenant (case- and whitespace-insensitive)
        - AND the user is NOT referenced as ``time_entries.user_id``
          or ``ingestion_timesheets.employee_id`` anywhere in the
          tenant

    Marks them ``is_active = False`` so they drop out of the user-
    management list while keeping audit history intact. No hard
    delete; if the orphans turn out to anchor records we missed,
    flipping ``is_active = True`` again restores them.

Usage::

    # Dry-run on a single tenant (default; reports candidate count)
    docker exec timesheet-api-1 sh -c "cd /app && PYTHONPATH=/app python scripts/cleanup_supervisor_users.py --slug acuent"

    # Apply on a single tenant
    docker exec timesheet-api-1 sh -c "cd /app && PYTHONPATH=/app python scripts/cleanup_supervisor_users.py --slug acuent --apply"

    # Dry-run across every active provisioned tenant
    docker exec timesheet-api-1 sh -c "cd /app && PYTHONPATH=/app python scripts/cleanup_supervisor_users.py"

Exit codes:
    0  - completed successfully (zero or more rows soft-deleted)
    1  - any failure (control plane unreachable, target DB
         unprovisioned, query failure, etc.)
    2  - usage error
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.models.control import ControlTenant
from app.models.control.tenant import ControlTenantStatus
from app.models.user import User


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("cleanup_supervisor_users")


# Predicate kept identical between the SQL probe and the unit test
# fixture. Editing it requires updating both.
ORPHAN_FILTER_SQL = """
WITH supervisor_names AS (
    SELECT DISTINCT lower(trim(supervisor_name)) AS name
    FROM time_entries
    WHERE supervisor_name IS NOT NULL AND trim(supervisor_name) <> ''
    UNION
    SELECT DISTINCT lower(trim(extracted_supervisor_name)) AS name
    FROM ingestion_timesheets
    WHERE extracted_supervisor_name IS NOT NULL
      AND trim(extracted_supervisor_name) <> ''
)
SELECT u.id, u.full_name, u.email
FROM users u
WHERE u.is_external = TRUE
  AND u.is_active = TRUE
  AND lower(trim(u.full_name)) IN (SELECT name FROM supervisor_names)
  AND NOT EXISTS (SELECT 1 FROM time_entries te WHERE te.user_id = u.id)
  AND NOT EXISTS (SELECT 1 FROM ingestion_timesheets it WHERE it.employee_id = u.id)
"""


def _tenant_db_url(db_name: str) -> str:
    """Build the per-tenant URL by swapping the database name on the
    shared connection URL. Same shape as the other ops scripts."""
    base = urlparse(settings.database_url)
    return f"{base.scheme}://{base.netloc}/{db_name}"


async def _load_targets(slug: Optional[str]) -> list[ControlTenant]:
    """Resolve which provisioned tenants to act on. Always filters to
    status=active and to tenants that have been provisioned (db_name
    set) — running cleanup on a tenant that's still on shared DB would
    be a no-op anyway."""
    engine = create_async_engine(settings.control_database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            stmt = select(ControlTenant).where(
                ControlTenant.status == ControlTenantStatus.active
            )
            if slug:
                stmt = stmt.where(ControlTenant.slug == slug)
            rows = (await session.execute(stmt)).scalars().all()
            return [t for t in rows if t.db_name]
    finally:
        await engine.dispose()


async def _cleanup_one(tenant: ControlTenant, apply: bool) -> int:
    """Run the orphan probe against one tenant DB. When ``apply`` is
    true, soft-delete the matched rows in a single transaction;
    otherwise just log them. Returns the number of orphan rows
    matched (whether or not they were updated)."""
    db_url = _tenant_db_url(tenant.db_name)
    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            rows = (await session.execute(text(ORPHAN_FILTER_SQL))).all()
            if not rows:
                logger.info("[%s] no orphan supervisor users found", tenant.slug)
                return 0

            for row in rows:
                logger.info(
                    "[%s] orphan id=%s full_name=%r email=%r",
                    tenant.slug, row.id, row.full_name, row.email,
                )

            if not apply:
                logger.info(
                    "[%s] dry-run: %d orphan(s) would be soft-deleted "
                    "(re-run with --apply to mark is_active=False)",
                    tenant.slug, len(rows),
                )
                return len(rows)

            ids = [row.id for row in rows]
            await session.execute(
                update(User)
                .where(User.id.in_(ids))
                .values(is_active=False)
            )
            await session.commit()
            logger.info(
                "[%s] soft-deleted %d orphan supervisor user(s)",
                tenant.slug, len(rows),
            )
            return len(rows)
    finally:
        await engine.dispose()


async def _run(slug: Optional[str], apply: bool) -> int:
    targets = await _load_targets(slug)
    if not targets:
        logger.info("no provisioned tenants matched (slug=%s)", slug)
        return 0

    logger.info(
        "%s on tenants: %s",
        "applying" if apply else "dry-run",
        ", ".join(t.slug for t in targets),
    )

    total = 0
    for tenant in targets:
        try:
            total += await _cleanup_one(tenant, apply)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] cleanup failed", tenant.slug)
            return 1

    logger.info(
        "done: %d orphan(s) %s across %d tenant(s)",
        total,
        "soft-deleted" if apply else "would be soft-deleted",
        len(targets),
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slug",
        help="Limit to one tenant slug (default: every active provisioned tenant)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually soft-delete the matched rows. Default is dry-run.",
    )
    args = parser.parse_args()

    try:
        rc = asyncio.run(_run(args.slug, args.apply))
    except KeyboardInterrupt:
        logger.warning("interrupted")
        rc = 130
    except Exception as exc:  # noqa: BLE001
        logger.exception("fatal")
        print(f"fatal: {exc}", flush=True)
        rc = 2
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
