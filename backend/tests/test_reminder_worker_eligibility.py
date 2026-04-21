"""
Regression tests for reminder worker recipient targeting and auto-lock.

Covers Fix 4 (internal reminder eligibility), Fix 5 (auto-lock eligibility),
and the tenant-timezone reminder window behavior added in WS2.

The worker now resolves current time through ``now_for_tenant``, so these
tests patch that helper to a deterministic aware datetime in the requested
tenant timezone.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - test shim
    return "JSON"


from app.core.security import get_password_hash
from app.core.timezone_utils import resolve_tz
from app.models.assignments import EmployeeManagerAssignment
from app.models.base import Base
from app.models.tenant import Tenant, TenantStatus
from app.models.tenant_settings import TenantSettings
from app.models.user import User, UserRole
from app.workers import reminder_worker
from app.workers.reminder_worker import _process_tenant_reminders


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "reminder_worker.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _freeze_worker_now(when: datetime):
    """Patch ``now_for_tenant`` inside reminder_worker to return ``when``."""

    def _frozen_now_for_tenant(tenant_timezone: str | None) -> datetime:
        return when.astimezone(resolve_tz(tenant_timezone))

    return patch.object(
        reminder_worker,
        "now_for_tenant",
        side_effect=_frozen_now_for_tenant,
    )


async def _make_tenant(session: AsyncSession) -> Tenant:
    tenant = Tenant(name="Tenant R", slug="tenant-r", status=TenantStatus.active)
    session.add(tenant)
    await session.flush()
    return tenant


async def _enable_internal_reminders(
    session: AsyncSession,
    tenant_id: int,
    *,
    lock_enabled: bool = False,
    deadline_day: str = "friday",
    deadline_time: str = "17:00",
) -> None:
    for key, value in [
        ("reminder_internal_enabled", "true"),
        ("reminder_internal_deadline_day", deadline_day),
        ("reminder_internal_deadline_time", deadline_time),
        ("reminder_internal_lock_enabled", "true" if lock_enabled else "false"),
        ("reminder_internal_recipients", "all"),
    ]:
        session.add(TenantSettings(tenant_id=tenant_id, key=key, value=value))
    await session.flush()


async def _make_employee(
    session: AsyncSession,
    tenant: Tenant,
    email: str,
    *,
    email_verified: bool = True,
    is_active: bool = True,
    timesheet_locked: bool = False,
    is_external: bool = False,
    created_at: datetime | None = None,
    with_manager: bool = True,
) -> User:
    user = User(
        tenant_id=tenant.id,
        email=email,
        username=email.split("@")[0],
        full_name=email,
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        is_active=is_active,
        email_verified=email_verified,
        timesheet_locked=timesheet_locked,
        is_external=is_external,
        has_changed_password=True,
    )
    if created_at is not None:
        user.created_at = created_at
    session.add(user)
    await session.flush()

    if with_manager:
        manager = User(
            tenant_id=tenant.id,
            email=f"mgr-{email}",
            username=f"mgr-{user.username}",
            full_name=f"Manager for {email}",
            hashed_password=get_password_hash("password"),
            role=UserRole.MANAGER,
            is_active=True,
            email_verified=True,
            has_changed_password=True,
        )
        session.add(manager)
        await session.flush()
        session.add(
            EmployeeManagerAssignment(employee_id=user.id, manager_id=manager.id)
        )
        await session.flush()
    return user


# The deadline is Friday 17:00 UTC; week_start for the frozen date is
# Monday 2026-04-13 00:00 UTC. A value inside the 14:00-14:15 early-reminder
# window gets us into the reminder path; a value past 17:00 gets us into the
# deadline-passed/lock path.
EARLY_WINDOW_NOW = datetime(2026, 4, 17, 14, 0, tzinfo=timezone.utc)
AFTER_DEADLINE_NOW = datetime(2026, 4, 17, 17, 5, tzinfo=timezone.utc)
WEEK_START_DT = datetime(2026, 4, 13, 0, 0, tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Fix 4 — internal reminder eligibility
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_internal_reminder_skips_user_with_no_manager(db_session: AsyncSession):
    tenant = await _make_tenant(db_session)
    await _enable_internal_reminders(db_session, tenant.id)
    await _make_employee(
        db_session, tenant, "orphan@example.com", with_manager=False
    )
    await db_session.commit()

    sent = AsyncMock()
    with _freeze_worker_now(EARLY_WINDOW_NOW), patch.object(
        reminder_worker, "send_email", sent
    ):
        await _process_tenant_reminders(tenant, db_session)

    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_internal_reminder_skips_unverified_user(db_session: AsyncSession):
    tenant = await _make_tenant(db_session)
    await _enable_internal_reminders(db_session, tenant.id)
    await _make_employee(
        db_session, tenant, "unverified@example.com", email_verified=False
    )
    await db_session.commit()

    sent = AsyncMock()
    with _freeze_worker_now(EARLY_WINDOW_NOW), patch.object(
        reminder_worker, "send_email", sent
    ):
        await _process_tenant_reminders(tenant, db_session)

    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_internal_reminder_skips_timesheet_locked_user(db_session: AsyncSession):
    tenant = await _make_tenant(db_session)
    await _enable_internal_reminders(db_session, tenant.id)
    await _make_employee(
        db_session, tenant, "locked@example.com", timesheet_locked=True
    )
    await db_session.commit()

    sent = AsyncMock()
    with _freeze_worker_now(EARLY_WINDOW_NOW), patch.object(
        reminder_worker, "send_email", sent
    ):
        await _process_tenant_reminders(tenant, db_session)

    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_internal_reminder_skips_external_user(db_session: AsyncSession):
    tenant = await _make_tenant(db_session)
    await _enable_internal_reminders(db_session, tenant.id)
    await _make_employee(
        db_session, tenant, "contractor@example.com", is_external=True
    )
    await db_session.commit()

    sent = AsyncMock()
    with _freeze_worker_now(EARLY_WINDOW_NOW), patch.object(
        reminder_worker, "send_email", sent
    ):
        await _process_tenant_reminders(tenant, db_session)

    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_internal_reminder_sends_to_legitimate_user(db_session: AsyncSession):
    tenant = await _make_tenant(db_session)
    await _enable_internal_reminders(db_session, tenant.id)
    emp = await _make_employee(db_session, tenant, "good@example.com")
    await db_session.commit()

    sent = AsyncMock()
    with _freeze_worker_now(EARLY_WINDOW_NOW), patch.object(
        reminder_worker, "send_email", sent
    ):
        await _process_tenant_reminders(tenant, db_session)

    sent.assert_awaited()
    # Confirm THIS user was the addressee.
    addressees = [call.kwargs.get("to_address") for call in sent.await_args_list]
    assert emp.email in addressees


# ─────────────────────────────────────────────────────────────────────────────
# Fix 5 — auto-lock eligibility
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_lock_skips_user_with_no_manager(db_session: AsyncSession):
    tenant = await _make_tenant(db_session)
    await _enable_internal_reminders(db_session, tenant.id, lock_enabled=True)
    emp = await _make_employee(
        db_session,
        tenant,
        "orphan@example.com",
        with_manager=False,
        created_at=WEEK_START_DT - timedelta(days=30),
    )
    await db_session.commit()

    with _freeze_worker_now(AFTER_DEADLINE_NOW), patch.object(
        reminder_worker, "send_email", AsyncMock()
    ):
        await _process_tenant_reminders(tenant, db_session)
    await db_session.refresh(emp)
    assert emp.timesheet_locked is False


@pytest.mark.asyncio
async def test_auto_lock_skips_unverified_user(db_session: AsyncSession):
    tenant = await _make_tenant(db_session)
    await _enable_internal_reminders(db_session, tenant.id, lock_enabled=True)
    emp = await _make_employee(
        db_session,
        tenant,
        "unverified@example.com",
        email_verified=False,
        created_at=WEEK_START_DT - timedelta(days=30),
    )
    await db_session.commit()

    with _freeze_worker_now(AFTER_DEADLINE_NOW), patch.object(
        reminder_worker, "send_email", AsyncMock()
    ):
        await _process_tenant_reminders(tenant, db_session)
    await db_session.refresh(emp)
    assert emp.timesheet_locked is False


@pytest.mark.asyncio
async def test_auto_lock_skips_user_created_after_week_start(db_session: AsyncSession):
    tenant = await _make_tenant(db_session)
    await _enable_internal_reminders(db_session, tenant.id, lock_enabled=True)
    emp = await _make_employee(
        db_session,
        tenant,
        "newhire@example.com",
        created_at=WEEK_START_DT + timedelta(days=2),
    )
    await db_session.commit()

    with _freeze_worker_now(AFTER_DEADLINE_NOW), patch.object(
        reminder_worker, "send_email", AsyncMock()
    ):
        await _process_tenant_reminders(tenant, db_session)
    await db_session.refresh(emp)
    assert emp.timesheet_locked is False


@pytest.mark.asyncio
async def test_auto_lock_skips_external_user(db_session: AsyncSession):
    tenant = await _make_tenant(db_session)
    await _enable_internal_reminders(db_session, tenant.id, lock_enabled=True)
    emp = await _make_employee(
        db_session,
        tenant,
        "contractor@example.com",
        is_external=True,
        created_at=WEEK_START_DT - timedelta(days=30),
    )
    await db_session.commit()

    with _freeze_worker_now(AFTER_DEADLINE_NOW), patch.object(
        reminder_worker, "send_email", AsyncMock()
    ):
        await _process_tenant_reminders(tenant, db_session)
    await db_session.refresh(emp)
    assert emp.timesheet_locked is False


@pytest.mark.asyncio
async def test_auto_lock_applies_to_legitimate_user(db_session: AsyncSession):
    tenant = await _make_tenant(db_session)
    await _enable_internal_reminders(db_session, tenant.id, lock_enabled=True)
    emp = await _make_employee(
        db_session,
        tenant,
        "eligible@example.com",
        created_at=WEEK_START_DT - timedelta(days=30),
    )
    await db_session.commit()

    with _freeze_worker_now(AFTER_DEADLINE_NOW), patch.object(
        reminder_worker, "send_email", AsyncMock()
    ):
        await _process_tenant_reminders(tenant, db_session)
    await db_session.refresh(emp)
    assert emp.timesheet_locked is True
    assert emp.timesheet_locked_reason is not None


@pytest.mark.asyncio
async def test_internal_lock_window_uses_tenant_timezone(db_session: AsyncSession):
    """
    2026-04-17 20:05 UTC is 16:05 in America/New_York.

    Under the old UTC-based logic that looked "past a 17:00 Friday deadline"
    and would auto-lock. Under tenant-aware logic it's still before 17:00 local,
    so no lock should occur yet.
    """
    tenant = await _make_tenant(db_session)
    tenant.timezone = "America/New_York"
    await _enable_internal_reminders(db_session, tenant.id, lock_enabled=True)
    emp = await _make_employee(
        db_session,
        tenant,
        "ny-employee@example.com",
        created_at=WEEK_START_DT - timedelta(days=30),
    )
    await db_session.commit()

    pre_local_deadline_utc = datetime(2026, 4, 17, 20, 5, tzinfo=timezone.utc)
    with _freeze_worker_now(pre_local_deadline_utc), patch.object(
        reminder_worker, "send_email", AsyncMock()
    ):
        await _process_tenant_reminders(tenant, db_session)

    await db_session.refresh(emp)
    assert emp.timesheet_locked is False
