"""
Tests for ``app.core.tenant_settings`` — the typed accessor over the
``TenantSettings`` key-value table and the ``setting_definitions`` catalog.

Covers: defaults fall-through, coercion from stored strings, unknown-key
errors, validation (type/min/max/enum), upsert behaviour, ActivityLog
auditing, and the ``TenantPolicy`` facade.
"""
from __future__ import annotations

from datetime import time as _time

import pytest
import pytest_asyncio
from sqlalchemy import select
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


from app.core.security import get_password_hash
from app.core.tenant_settings import (
    TENANT_SETTING_CHANGED,
    TenantPolicy,
    get_all_settings,
    get_public_settings,
    get_setting,
    set_setting,
)
from app.models.activity_log import ActivityLog
from app.models.base import Base
from app.models.tenant import Tenant, TenantStatus
from app.models.tenant_settings import TenantSettings
from app.models.user import User, UserRole
from app.seed_setting_definitions import seed_async


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'accessor.db'}"
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


@pytest_asyncio.fixture
async def tenant(db_session: AsyncSession) -> Tenant:
    tenant = Tenant(name="Tenant A", slug="tenant-a", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest_asyncio.fixture
async def actor(db_session: AsyncSession, tenant: Tenant) -> User:
    user = User(
        tenant_id=tenant.id,
        email="admin@a.example",
        username="admin-a",
        full_name="Admin A",
        hashed_password=get_password_hash("password"),
        role=UserRole.ADMIN,
        is_active=True,
        email_verified=True,
        has_changed_password=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


# ─────────────────────────────────────────────────────────────────────────────
# get_setting
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_setting_returns_default_when_no_row(
    db_session: AsyncSession, tenant: Tenant
):
    value = await get_setting(db_session, tenant.id, "max_hours_per_day")
    assert value == 12.0
    assert isinstance(value, float)


@pytest.mark.asyncio
async def test_get_setting_returns_stored_value_typed(
    db_session: AsyncSession, tenant: Tenant
):
    db_session.add(
        TenantSettings(tenant_id=tenant.id, key="max_hours_per_day", value="10")
    )
    await db_session.commit()
    value = await get_setting(db_session, tenant.id, "max_hours_per_day")
    assert value == 10.0
    assert isinstance(value, float)


@pytest.mark.asyncio
async def test_get_setting_coerces_legacy_bool_strings(
    db_session: AsyncSession, tenant: Tenant
):
    """Rows written by the legacy PATCH path stored bools as bare
    'true'/'false' (from ``str(True)``). The accessor must still parse them."""
    db_session.add(
        TenantSettings(
            tenant_id=tenant.id,
            key="allow_partial_week_submit",
            value="True",
        )
    )
    await db_session.commit()
    value = await get_setting(
        db_session, tenant.id, "allow_partial_week_submit"
    )
    assert value is True


@pytest.mark.asyncio
async def test_get_setting_raises_for_unknown_key(
    db_session: AsyncSession, tenant: Tenant
):
    with pytest.raises(KeyError):
        await get_setting(db_session, tenant.id, "nonexistent_key")


# ─────────────────────────────────────────────────────────────────────────────
# set_setting validation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_setting_validates_type(
    db_session: AsyncSession, tenant: Tenant, actor: User
):
    with pytest.raises(ValueError):
        await set_setting(
            db_session, tenant.id, "max_hours_per_day", "banana", actor.id
        )


@pytest.mark.asyncio
async def test_set_setting_validates_min(
    db_session: AsyncSession, tenant: Tenant, actor: User
):
    with pytest.raises(ValueError):
        await set_setting(
            db_session, tenant.id, "max_hours_per_day", -1.0, actor.id
        )


@pytest.mark.asyncio
async def test_set_setting_validates_max(
    db_session: AsyncSession, tenant: Tenant, actor: User
):
    with pytest.raises(ValueError):
        await set_setting(
            db_session, tenant.id, "max_hours_per_day", 999.0, actor.id
        )


@pytest.mark.asyncio
async def test_set_setting_validates_enum(
    db_session: AsyncSession, tenant: Tenant, actor: User
):
    with pytest.raises(ValueError):
        await set_setting(db_session, tenant.id, "week_start_day", 5, actor.id)


@pytest.mark.asyncio
async def test_set_setting_validates_time_format(
    db_session: AsyncSession, tenant: Tenant, actor: User
):
    with pytest.raises(ValueError):
        await set_setting(
            db_session,
            tenant.id,
            "reminder_internal_deadline_time",
            "25:00",
            actor.id,
        )


@pytest.mark.asyncio
async def test_set_setting_raises_for_unknown_key(
    db_session: AsyncSession, tenant: Tenant, actor: User
):
    with pytest.raises(KeyError):
        await set_setting(
            db_session, tenant.id, "nonexistent_key", "value", actor.id
        )


# ─────────────────────────────────────────────────────────────────────────────
# set_setting success paths + audit log
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_setting_writes_row_and_logs_activity(
    db_session: AsyncSession, tenant: Tenant, actor: User
):
    await set_setting(
        db_session, tenant.id, "max_hours_per_day", 10.0, actor.id
    )
    await db_session.commit()

    stored = await db_session.execute(
        select(TenantSettings).where(
            TenantSettings.tenant_id == tenant.id,
            TenantSettings.key == "max_hours_per_day",
        )
    )
    row = stored.scalar_one()
    assert row.value in ("10.0", "10")  # JSON serialisation varies

    typed = await get_setting(db_session, tenant.id, "max_hours_per_day")
    assert typed == 10.0

    log = await db_session.execute(
        select(ActivityLog)
        .where(ActivityLog.activity_type == TENANT_SETTING_CHANGED)
        .where(ActivityLog.tenant_id == tenant.id)
    )
    entries = list(log.scalars().all())
    assert len(entries) == 1
    meta = entries[0].metadata_json or {}
    assert meta["key"] == "max_hours_per_day"
    # No TenantSettings row existed before; spec says before=None in that case.
    assert meta["before"] is None
    assert meta["after"] == 10.0
    assert entries[0].actor_user_id == actor.id
    assert entries[0].visibility_scope == "TENANT_ADMIN"


@pytest.mark.asyncio
async def test_set_setting_updates_existing_row(
    db_session: AsyncSession, tenant: Tenant, actor: User
):
    db_session.add(
        TenantSettings(tenant_id=tenant.id, key="max_hours_per_day", value="8")
    )
    await db_session.commit()

    await set_setting(
        db_session, tenant.id, "max_hours_per_day", 10.0, actor.id
    )
    await db_session.commit()

    typed = await get_setting(db_session, tenant.id, "max_hours_per_day")
    assert typed == 10.0

    log = await db_session.execute(
        select(ActivityLog).where(
            ActivityLog.activity_type == TENANT_SETTING_CHANGED
        )
    )
    entry = log.scalars().one()
    meta = entry.metadata_json or {}
    assert meta["before"] == 8.0
    assert meta["after"] == 10.0


@pytest.mark.asyncio
async def test_set_setting_bool_coerces_string(
    db_session: AsyncSession, tenant: Tenant, actor: User
):
    returned = await set_setting(
        db_session,
        tenant.id,
        "allow_partial_week_submit",
        "true",
        actor.id,
    )
    assert returned is True


# ─────────────────────────────────────────────────────────────────────────────
# TenantPolicy
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_policy_for_tenant_returns_typed_object(
    db_session: AsyncSession, tenant: Tenant
):
    policy = await TenantPolicy.for_tenant(db_session, tenant.id)
    assert isinstance(policy.max_hours_per_day, float)
    assert isinstance(policy.allow_partial_week_submit, bool)
    assert isinstance(policy.week_start_day, int)
    assert isinstance(policy.daily_submission_deadline_time, _time)
    assert policy.daily_submission_deadline_time == _time(10, 0)


@pytest.mark.asyncio
async def test_tenant_policy_reflects_overrides(
    db_session: AsyncSession, tenant: Tenant, actor: User
):
    await set_setting(
        db_session, tenant.id, "max_hours_per_day", 6.0, actor.id
    )
    await set_setting(
        db_session, tenant.id, "week_start_day", 1, actor.id
    )
    await db_session.commit()

    policy = await TenantPolicy.for_tenant(db_session, tenant.id)
    assert policy.max_hours_per_day == 6.0
    assert policy.week_start_day == 1


# ─────────────────────────────────────────────────────────────────────────────
# Public settings / all settings
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_public_settings_excludes_non_public(
    db_session: AsyncSession, tenant: Tenant
):
    public = await get_public_settings(db_session, tenant.id)
    assert "smtp_password" not in public
    assert "max_failed_login_attempts" not in public
    assert "week_start_day" in public


@pytest.mark.asyncio
async def test_get_all_settings_returns_every_catalog_key(
    db_session: AsyncSession, tenant: Tenant
):
    all_settings = await get_all_settings(db_session, tenant.id)
    # Spot-check a representative sample across categories.
    for key in [
        "time_entry_past_days",
        "time_off_future_days",
        "max_failed_login_attempts",
        "reminder_internal_deadline_time",
        "notification_ttl_days",
        "smtp_host",
    ]:
        assert key in all_settings, f"{key} missing from all-settings"
