"""
Regression tests for reminder worker recipient targeting and auto-lock.

Covers Fix 4 (internal reminder eligibility) and Fix 5 (auto-lock eligibility).
The worker's state machine picks a "window" based on wall-clock time, so the
tests force ``datetime.now`` inside the worker module to a deterministic value
that falls inside either the pre-deadline reminder window or the post-deadline
lock window as each test needs.
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


class _FrozenDatetime(datetime):
    """Subclass so ``datetime.now(tz)`` returns a deterministic value inside
    the worker while ``datetime(...)`` continues to construct real instances."""

    _frozen: datetime = datetime(2026, 4, 17, 14, 30, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if tz is None:
            return cls._frozen.replace(tzinfo=None)
        return cls._frozen.astimezone(tz)


def _freeze_worker_now(when: datetime):
    """Patch `datetime` inside reminder_worker so now() returns ``when``."""
    _FrozenDatetime._frozen = when
    return patch.object(reminder_worker, "datetime", _FrozenDatetime)


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
        await _process_tenant_reminders(tenant.id, db_session)

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
        await _process_tenant_reminders(tenant.id, db_session)

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
        await _process_tenant_reminders(tenant.id, db_session)

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
        await _process_tenant_reminders(tenant.id, db_session)

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
        await _process_tenant_reminders(tenant.id, db_session)

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
        await _process_tenant_reminders(tenant.id, db_session)
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
        await _process_tenant_reminders(tenant.id, db_session)
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
        await _process_tenant_reminders(tenant.id, db_session)
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
        await _process_tenant_reminders(tenant.id, db_session)
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
        await _process_tenant_reminders(tenant.id, db_session)
    await db_session.refresh(emp)
    assert emp.timesheet_locked is True
    assert emp.timesheet_locked_reason is not None
