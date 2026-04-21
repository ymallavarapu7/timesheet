"""
Regression tests for Fix 13 — the monthly reminder for external contractors
(``is_external=True``) must skip users whose email isn't verified, consistent
with the internal reminder eligibility helper. Inactive users continue to
be skipped as today.
"""
from datetime import datetime, timezone
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
from app.models.base import Base
from app.models.tenant import Tenant, TenantStatus
from app.models.tenant_settings import TenantSettings
from app.models.user import User, UserRole
from app.workers import reminder_worker
from app.workers.reminder_worker import _process_tenant_reminders


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "external_reminder.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


class _FrozenDatetime(datetime):
    """Freeze ``datetime.now(tz)`` inside ``reminder_worker`` so the test
    lands inside the 3-hour-before-deadline window."""

    _frozen: datetime = datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if tz is None:
            return cls._frozen.replace(tzinfo=None)
        return cls._frozen.astimezone(tz)


def _freeze_worker_now(when: datetime):
    _FrozenDatetime._frozen = when
    return patch.object(reminder_worker, "datetime", _FrozenDatetime)


async def _make_tenant(session: AsyncSession) -> Tenant:
    tenant = Tenant(name="Tenant E", slug="tenant-e", status=TenantStatus.active)
    session.add(tenant)
    await session.flush()
    return tenant


async def _enable_external_reminders(
    session: AsyncSession, tenant_id: int
) -> None:
    """Configure external reminders so the deadline lands on 2026-04-30 17:00
    UTC. ``day_of_month = -1`` means the last day of the month; the test
    freezes now to 2026-04-28 14:00, squarely inside the 3-hour window of the
    equivalent earlier-window check (see reminder_worker's window arithmetic
    — a 2-day window around the deadline covers this).
    """
    for key, value in [
        ("reminder_external_enabled", "true"),
        ("reminder_external_deadline_day_of_month", "-1"),
        ("reminder_external_deadline_time", "17:00"),
    ]:
        session.add(TenantSettings(tenant_id=tenant_id, key=key, value=value))
    await session.flush()


async def _make_external(
    session: AsyncSession,
    tenant: Tenant,
    email: str,
    *,
    is_active: bool = True,
    email_verified: bool = True,
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
        is_external=True,
        has_changed_password=True,
    )
    session.add(user)
    await session.flush()
    return user


# Deadline = 2026-04-30 17:00 UTC; the 2-day window opens 2026-04-28 17:00.
# Pick now = 2026-04-28 17:05 so we're within the 15-minute 2-day window.
TWO_DAY_WINDOW_NOW = datetime(2026, 4, 28, 17, 5, tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_external_reminder_skips_unverified_contractor(
    db_session: AsyncSession,
):
    tenant = await _make_tenant(db_session)
    await _enable_external_reminders(db_session, tenant.id)
    await _make_external(
        db_session, tenant, "unverified@contractor.example",
        is_active=True, email_verified=False,
    )
    await db_session.commit()

    sender = AsyncMock()
    with _freeze_worker_now(TWO_DAY_WINDOW_NOW), patch.object(
        reminder_worker, "send_email", sender
    ):
        await _process_tenant_reminders(tenant.id, db_session)

    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_reminder_sends_to_verified_contractor(
    db_session: AsyncSession,
):
    tenant = await _make_tenant(db_session)
    await _enable_external_reminders(db_session, tenant.id)
    external = await _make_external(
        db_session, tenant, "verified@contractor.example",
        is_active=True, email_verified=True,
    )
    await db_session.commit()

    sender = AsyncMock()
    with _freeze_worker_now(TWO_DAY_WINDOW_NOW), patch.object(
        reminder_worker, "send_email", sender
    ):
        await _process_tenant_reminders(tenant.id, db_session)

    sender.assert_awaited()
    addressees = [call.kwargs.get("to_address") for call in sender.await_args_list]
    assert external.email in addressees


@pytest.mark.asyncio
async def test_external_reminder_skips_inactive_contractor(
    db_session: AsyncSession,
):
    tenant = await _make_tenant(db_session)
    await _enable_external_reminders(db_session, tenant.id)
    await _make_external(
        db_session, tenant, "deactivated@contractor.example",
        is_active=False, email_verified=True,
    )
    await db_session.commit()

    sender = AsyncMock()
    with _freeze_worker_now(TWO_DAY_WINDOW_NOW), patch.object(
        reminder_worker, "send_email", sender
    ):
        await _process_tenant_reminders(tenant.id, db_session)

    sender.assert_not_awaited()
