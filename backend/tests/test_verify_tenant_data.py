"""Tests for the tenant-data verification script.

The script is a thin per-table count comparison; the only logic worth
guarding is the filter-spec dispatch (so a typo in the runner table
list doesn't quietly skip a table) and the mismatch detection. We use
in-memory SQLite for both source and target so the test exercises the
real SQL path without needing live Postgres.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from scripts import verify_tenant_data as verifier


@pytest.mark.asyncio
async def test_src_count_dispatches_filter_specs(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'src.db'}")
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE widgets (id INTEGER PRIMARY KEY, tenant_id INTEGER)"
            ))
            await conn.execute(text(
                "INSERT INTO widgets (id, tenant_id) VALUES (1,1),(2,1),(3,2)"
            ))
        async with engine.connect() as conn:
            assert await verifier._src_count(conn, "widgets", "all", 1) == 3
            assert await verifier._src_count(conn, "widgets", "tenant_id", 1) == 2
            assert await verifier._src_count(conn, "widgets", "id", 1) == 1
            n = await verifier._src_count(
                conn, "widgets", "where:tenant_id = :tid OR id = 3", 1
            )
            assert n == 3
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_src_count_rejects_unknown_filter(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'src.db'}")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
        async with engine.connect() as conn:
            with pytest.raises(ValueError):
                await verifier._src_count(conn, "t", "bogus", 1)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tgt_count_returns_zero_for_empty(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'tgt.db'}")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
        async with engine.connect() as conn:
            assert await verifier._tgt_count(conn, "t") == 0
    finally:
        await engine.dispose()
