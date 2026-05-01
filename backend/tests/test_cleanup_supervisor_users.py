"""Tests for the orphan-supervisor cleanup predicate.

The script's ``ORPHAN_FILTER_SQL`` is the only piece of logic worth
testing in isolation — the surrounding code (target loading, soft-
delete write, dry-run flag plumbing) is straightforward. We seed an
in-memory SQLite with the three relevant tables, run the predicate,
and assert which rows came back.

SQLite supports the CTE + ``NOT EXISTS`` subquery shape unchanged from
Postgres, so the same SQL string runs without translation. If we ever
need a Postgres-only feature in the predicate, this test will fail
loudly and we'll know to add a Postgres fixture.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from scripts.cleanup_supervisor_users import ORPHAN_FILTER_SQL


SCHEMA_SQL = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT,
    is_external INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE time_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    supervisor_name TEXT
);
CREATE TABLE ingestion_timesheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER,
    extracted_supervisor_name TEXT
);
"""


@pytest_asyncio.fixture
async def session(tmp_path) -> AsyncSession:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cleanup.db'}")
    async with engine.begin() as conn:
        for stmt in SCHEMA_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _insert_user(
    session: AsyncSession,
    *,
    full_name: str,
    is_external: bool,
    is_active: bool = True,
    email: str | None = None,
) -> int:
    result = await session.execute(
        text("INSERT INTO users (full_name, email, is_external, is_active) VALUES (:n, :e, :ex, :ac)"),
        {"n": full_name, "e": email, "ex": int(is_external), "ac": int(is_active)},
    )
    last = (await session.execute(text("SELECT last_insert_rowid()"))).scalar_one()
    await session.commit()
    return int(last)


@pytest.mark.asyncio
async def test_orphan_with_supervisor_match_and_no_anchors_is_picked(session):
    """Happy path: external user named like an extracted supervisor,
    no time entries / ingestion rows pointing at them — should match."""
    uid = await _insert_user(session, full_name="Jianli Xiao", is_external=True)
    await session.execute(
        text("INSERT INTO ingestion_timesheets (employee_id, extracted_supervisor_name) VALUES (NULL, 'Jianli Xiao')"),
    )
    await session.commit()

    rows = (await session.execute(text(ORPHAN_FILTER_SQL))).all()
    assert [r.id for r in rows] == [uid]


@pytest.mark.asyncio
async def test_match_is_case_and_whitespace_insensitive(session):
    uid = await _insert_user(session, full_name="  jianli xiao  ", is_external=True)
    await session.execute(
        text("INSERT INTO time_entries (user_id, supervisor_name) VALUES (NULL, 'JIANLI XIAO')"),
    )
    await session.commit()

    rows = (await session.execute(text(ORPHAN_FILTER_SQL))).all()
    assert [r.id for r in rows] == [uid]


@pytest.mark.asyncio
async def test_internal_users_are_never_matched(session):
    """is_external=False rows are real tenant users; never touch them
    even if the name happens to collide with a supervisor."""
    await _insert_user(session, full_name="Real Manager", is_external=False)
    await session.execute(
        text("INSERT INTO ingestion_timesheets (employee_id, extracted_supervisor_name) VALUES (NULL, 'Real Manager')"),
    )
    await session.commit()

    rows = (await session.execute(text(ORPHAN_FILTER_SQL))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_external_user_anchored_by_time_entry_is_skipped(session):
    """If the external user has any time_entry pointing at them, they
    are anchoring real data — leave them alone."""
    uid = await _insert_user(session, full_name="Edge Case", is_external=True)
    await session.execute(
        text("INSERT INTO time_entries (user_id, supervisor_name) VALUES (:uid, 'Edge Case')"),
        {"uid": uid},
    )
    await session.commit()

    rows = (await session.execute(text(ORPHAN_FILTER_SQL))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_external_user_anchored_by_ingestion_employee_is_skipped(session):
    uid = await _insert_user(session, full_name="Edge Case", is_external=True)
    await session.execute(
        text("INSERT INTO ingestion_timesheets (employee_id, extracted_supervisor_name) VALUES (:uid, 'Edge Case')"),
        {"uid": uid},
    )
    await session.commit()

    rows = (await session.execute(text(ORPHAN_FILTER_SQL))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_inactive_external_users_are_skipped(session):
    """Already-soft-deleted rows must not match a second time —
    re-running the script should be a no-op against a clean DB."""
    await _insert_user(session, full_name="Already Cleaned", is_external=True, is_active=False)
    await session.execute(
        text("INSERT INTO ingestion_timesheets (employee_id, extracted_supervisor_name) VALUES (NULL, 'Already Cleaned')"),
    )
    await session.commit()

    rows = (await session.execute(text(ORPHAN_FILTER_SQL))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_external_with_no_supervisor_name_match_is_skipped(session):
    """External users that aren't supervisor look-alikes (e.g.,
    legitimate ingestion-created employees) must not match."""
    await _insert_user(session, full_name="Real External Employee", is_external=True)
    await session.execute(
        text("INSERT INTO ingestion_timesheets (employee_id, extracted_supervisor_name) VALUES (NULL, 'Some Other Supervisor')"),
    )
    await session.commit()

    rows = (await session.execute(text(ORPHAN_FILTER_SQL))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_blank_supervisor_names_are_ignored(session):
    """Empty / whitespace-only supervisor strings must not produce
    a name set entry that could match every blank-named external."""
    await _insert_user(session, full_name="", is_external=True)
    await session.execute(
        text("INSERT INTO ingestion_timesheets (employee_id, extracted_supervisor_name) VALUES (NULL, '   ')"),
    )
    await session.commit()

    rows = (await session.execute(text(ORPHAN_FILTER_SQL))).all()
    assert rows == []
