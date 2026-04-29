"""One-time data migration: shared DB → control-plane DB (Phase 3.A).

Copies the rows that belong on the control plane out of the shared
``timesheet_db`` and into ``acufy_control``:

- ``tenants``                 → ``acufy_control.tenants``
- ``platform_settings``       → ``acufy_control.platform_settings``
- users where role = 'PLATFORM_ADMIN' → ``acufy_control.platform_admins``

The script is idempotent: it uses ``ON CONFLICT DO NOTHING`` semantics
keyed on the natural unique columns (slug for tenants, email for
admins, key for settings). Run it as many times as you need; the
output reports what was copied vs. skipped.

The source rows in ``timesheet_db`` are NOT deleted by this script.
We keep them for one release as a safety net. A later cleanup commit
will drop the legacy tables.

Usage::

    docker exec timesheet-api-1 sh -c "cd /app && PYTHONPATH=/app python scripts/migrate_control_plane.py"

Exit codes::

    0  — migration ran cleanly (zero or more rows copied)
    1  — anything else (connection error, schema mismatch, partial run)
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.models.control import (
    ControlPlatformSettings,
    ControlTenant,
    PlatformAdmin,
)


async def _copy_tenants(src: AsyncSession, dst: AsyncSession) -> tuple[int, int]:
    rows = (await src.execute(text(
        "SELECT id, name, slug, status, ingestion_enabled, max_mailboxes, "
        "timezone, created_at, updated_at FROM tenants"
    ))).mappings().all()

    copied = 0
    skipped = 0
    for row in rows:
        existing = await dst.scalar(
            select(ControlTenant).where(ControlTenant.slug == row["slug"])
        )
        if existing is not None:
            skipped += 1
            continue
        dst.add(ControlTenant(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            # Cast to the local enum value; the names match.
            status=row["status"],
            ingestion_enabled=row["ingestion_enabled"],
            max_mailboxes=row["max_mailboxes"],
            timezone=row["timezone"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        ))
        copied += 1
    await dst.flush()
    return copied, skipped


async def _copy_platform_settings(src: AsyncSession, dst: AsyncSession) -> tuple[int, int]:
    rows = (await src.execute(text(
        "SELECT key, value, created_at, updated_at FROM platform_settings"
    ))).mappings().all()

    copied = 0
    skipped = 0
    for row in rows:
        existing = await dst.scalar(
            select(ControlPlatformSettings).where(
                ControlPlatformSettings.key == row["key"]
            )
        )
        if existing is not None:
            skipped += 1
            continue
        dst.add(ControlPlatformSettings(
            key=row["key"],
            value=row["value"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        ))
        copied += 1
    await dst.flush()
    return copied, skipped


async def _copy_platform_admins(src: AsyncSession, dst: AsyncSession) -> tuple[int, int]:
    rows = (await src.execute(text(
        "SELECT email, username, full_name, hashed_password, is_active, "
        "has_changed_password, email_verified, created_at, updated_at "
        "FROM users WHERE role = 'PLATFORM_ADMIN'"
    ))).mappings().all()

    copied = 0
    skipped = 0
    for row in rows:
        existing = await dst.scalar(
            select(PlatformAdmin).where(PlatformAdmin.email == row["email"])
        )
        if existing is not None:
            skipped += 1
            continue
        dst.add(PlatformAdmin(
            email=row["email"],
            username=row["username"],
            full_name=row["full_name"],
            hashed_password=row["hashed_password"],
            is_active=row["is_active"],
            has_changed_password=row["has_changed_password"],
            email_verified=row["email_verified"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        ))
        copied += 1
    await dst.flush()
    return copied, skipped


async def _run() -> int:
    src_engine = create_async_engine(settings.database_url)
    dst_engine = create_async_engine(settings.control_database_url)

    try:
        async with src_engine.connect() as src_conn, dst_engine.connect() as dst_conn:
            src_session = AsyncSession(bind=src_conn, expire_on_commit=False)
            dst_session = AsyncSession(bind=dst_conn, expire_on_commit=False)
            try:
                async with dst_conn.begin():
                    t_copied, t_skipped = await _copy_tenants(src_session, dst_session)
                    s_copied, s_skipped = await _copy_platform_settings(src_session, dst_session)
                    a_copied, a_skipped = await _copy_platform_admins(src_session, dst_session)
            finally:
                await src_session.close()
                await dst_session.close()
    finally:
        await src_engine.dispose()
        await dst_engine.dispose()

    print(f"tenants:          copied={t_copied}, skipped={t_skipped}")
    print(f"platform_settings: copied={s_copied}, skipped={s_skipped}")
    print(f"platform_admins:  copied={a_copied}, skipped={a_skipped}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
