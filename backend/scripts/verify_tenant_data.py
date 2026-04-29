"""Verify a tenant's per-DB copy matches the shared source DB.

Run after ``migrate_tenant_data.py``. For every table the migration
script copies, compare ``SELECT count(*)`` in the source (filtered to
the tenant) against ``SELECT count(*)`` in the target. Reports any
mismatches and exits non-zero on the first divergence.

Usage::

    docker exec timesheet-api-1 sh -c "cd /app && PYTHONPATH=/app python scripts/verify_tenant_data.py <slug>"

Exit codes:
    0  - every table matches
    1  - one or more tables disagree (details on stdout)
    2  - tenant not found / target DB missing
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from urllib.parse import urlparse

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.models.control import ControlTenant
from scripts.migrate_tenant_data import TABLES, _tenant_db_name


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("verify_tenant_data")


def _tenant_db_url(db_name: str) -> str:
    base = urlparse(settings.database_url)
    return f"{base.scheme}://{base.netloc}/{db_name}"


async def _resolve_tenant_id(slug: str) -> int:
    engine = create_async_engine(settings.control_database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as s:
            row = (await s.execute(
                select(ControlTenant).where(ControlTenant.slug == slug)
            )).scalar_one_or_none()
            if row is None or row.db_name is None:
                raise SystemExit(2)
            return row.id
    finally:
        await engine.dispose()


async def _src_count(conn, table: str, filter_spec: str, tenant_id: int) -> int:
    if filter_spec == "all":
        sql = f'SELECT count(*) FROM "{table}"'
        params: dict = {}
    elif filter_spec == "tenant_id":
        sql = f'SELECT count(*) FROM "{table}" WHERE tenant_id = :tid'
        params = {"tid": tenant_id}
    elif filter_spec == "id":
        sql = f'SELECT count(*) FROM "{table}" WHERE id = :tid'
        params = {"tid": tenant_id}
    elif filter_spec.startswith("where:"):
        sql = f'SELECT count(*) FROM "{table}" WHERE {filter_spec[6:]}'
        params = {"tid": tenant_id}
    else:
        raise ValueError(filter_spec)
    return (await conn.execute(text(sql), params)).scalar_one()


async def _tgt_count(conn, table: str) -> int:
    return (
        await conn.execute(text(f'SELECT count(*) FROM "{table}"'))
    ).scalar_one()


async def _verify(slug: str) -> int:
    tenant_id = await _resolve_tenant_id(slug)
    src_url = settings.database_url
    tgt_url = _tenant_db_url(_tenant_db_name(slug))

    src_engine = create_async_engine(src_url)
    tgt_engine = create_async_engine(tgt_url)
    mismatches: list[tuple[str, int, int]] = []
    try:
        async with src_engine.connect() as src, tgt_engine.connect() as tgt:
            for table, filter_spec in TABLES:
                s = await _src_count(src, table, filter_spec, tenant_id)
                t = await _tgt_count(tgt, table)
                marker = "ok " if s == t else "MISMATCH"
                logger.info("%s  %-32s src=%-6d tgt=%d", marker, table, s, t)
                if s != t:
                    mismatches.append((table, s, t))
    finally:
        await src_engine.dispose()
        await tgt_engine.dispose()

    if mismatches:
        logger.error("verification failed: %d table(s) diverge", len(mismatches))
        return 1
    logger.info("verified: all %d tables match", len(TABLES))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_verify(args.slug)))


if __name__ == "__main__":
    main()
