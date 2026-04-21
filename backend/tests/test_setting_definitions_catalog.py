"""
Tests for the ``setting_definitions`` seed catalog.

Covers:
  * every key the codebase currently reads from ``TenantSettings`` is in
    the catalog;
  * every catalog row has the required metadata (non-null label/description/
    default_value);
  * the seed is idempotent — running it twice produces the same result.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - test shim
    return "JSON"


from app.models.base import Base
from app.models.setting_definition import SettingDefinition  # noqa: F401
from app.seed_setting_definitions import CATALOG, seed_async


EXPECTED_KEYS = {
    # time_entry
    "time_entry_past_days",
    "time_entry_future_days",
    "max_hours_per_entry",
    "max_hours_per_day",
    "max_hours_per_week",
    "min_submit_weekly_hours",
    "allow_partial_week_submit",
    "week_start_day",
    "tenant_default_timezone",
    # time_off
    "time_off_past_days",
    "time_off_future_days",
    "time_off_advance_notice_days",
    "time_off_max_consecutive_days",
    "allow_overlapping_time_off",
    # security
    "max_failed_login_attempts",
    "lockout_duration_minutes",
    # reminders
    "reminder_internal_enabled",
    "reminder_internal_deadline_day",
    "reminder_internal_deadline_time",
    "reminder_internal_lock_enabled",
    "reminder_internal_recipients",
    "reminder_external_enabled",
    "reminder_external_deadline_day_of_month",
    "reminder_external_deadline_time",
    # notifications
    "notification_ttl_days",
    "approval_history_ttl_days",
    "daily_submission_deadline_time",
    "missing_yesterday_notify_after_hour",
    "manager_missing_team_notify_after_hour",
    # email
    "smtp_host",
    "smtp_port",
    "smtp_username",
    "smtp_password",
    "smtp_from_address",
    "smtp_from_name",
    "smtp_use_tls",
}


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'catalog.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        await seed_async(session)
        await session.commit()
        yield session
    await engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_known_keys_are_in_catalog(db_session: AsyncSession):
    result = await db_session.execute(select(SettingDefinition))
    rows = list(result.scalars().all())
    keys = {row.key for row in rows}

    missing = EXPECTED_KEYS - keys
    assert not missing, f"catalog is missing expected keys: {missing}"

    # No row may have null label / description / default_value.
    for row in rows:
        assert row.label, f"row {row.key} has empty label"
        assert row.description, f"row {row.key} has empty description"
        assert row.default_value is not None, (
            f"row {row.key} has null default_value"
        )


@pytest.mark.asyncio
async def test_catalog_dict_matches_db_after_seed(db_session: AsyncSession):
    """The in-memory CATALOG dict and the seeded DB rows must agree on keys."""
    result = await db_session.execute(select(SettingDefinition.key))
    db_keys = {key for key, in result.all()}
    assert db_keys == set(CATALOG.keys())


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session: AsyncSession):
    """Re-running the seed must not duplicate rows or clobber existing ones."""
    count_before = await db_session.scalar(
        select(func.count(SettingDefinition.key))
    )
    await seed_async(db_session)
    await db_session.commit()
    count_after = await db_session.scalar(
        select(func.count(SettingDefinition.key))
    )
    assert count_before == count_after
