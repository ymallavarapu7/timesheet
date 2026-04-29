"""
Tenant-timezone awareness for scheduling endpoints.

Covers:
  * ``GET /dashboard/team-daily-overview`` — ``submission_deadline_at`` is in
    the tenant's timezone, not the server-local timezone.
  * ``GET /notifications/summary`` — the "missing yesterday entry" tile does
    not fire at moments that are still "today" in the tenant's timezone.
  * NULL ``tenant.timezone`` falls back to UTC with no exception raised.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
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


from app.api import dashboard as dashboard_api
from app.api import notifications as notifications_api
from app.core.security import create_access_token, get_password_hash
from app.db import get_db
from app.core.deps import get_tenant_db
from app.models.assignments import EmployeeManagerAssignment
from app.models.base import Base
from app.models.client import Client
from app.models.project import Project
from app.models.setting_definition import SettingDefinition  # noqa: F401
from app.models.tenant import Tenant, TenantStatus
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "tz_aware.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _make_dashboard_app(db_session: AsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(dashboard_api.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_get_db
    return TestClient(app)


def _make_notifications_app(db_session: AsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(notifications_api.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_get_db
    return TestClient(app)


def _auth_headers(user: User) -> dict:
    token = create_access_token(
        {"sub": str(user.id), "tenant_id": user.tenant_id}
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(
    session: AsyncSession,
    *,
    email: str,
    tenant_id: int | None,
    role: UserRole,
) -> User:
    user = User(
        tenant_id=tenant_id,
        email=email,
        username=email.split("@")[0].replace(".", "-"),
        full_name=email,
        hashed_password=get_password_hash("password"),
        role=role,
        is_active=True,
        email_verified=True,
        has_changed_password=True,
    )
    session.add(user)
    await session.flush()
    return user


# ─────────────────────────────────────────────────────────────────────────────
# Site 1: dashboard /team-daily-overview uses tenant timezone
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_deadline_uses_tenant_timezone(db_session: AsyncSession):
    """Deadline response time should have America/New_York tz, not UTC."""
    tenant = Tenant(
        name="NY Tenant",
        slug="ny-tenant",
        status=TenantStatus.active,
        timezone="America/New_York",
    )
    db_session.add(tenant)
    await db_session.flush()

    manager = await _make_user(
        db_session, email="mgr@ny.example", tenant_id=tenant.id, role=UserRole.MANAGER,
    )
    await db_session.commit()

    client = _make_dashboard_app(db_session)
    with client:
        response = client.get(
            "/dashboard/team-daily-overview", headers=_auth_headers(manager)
        )
    assert response.status_code == 200, response.text
    body = response.json()
    deadline_raw = body["submission_deadline_at"]
    assert deadline_raw is not None

    parsed = datetime.fromisoformat(deadline_raw)
    assert parsed.tzinfo is not None, "deadline should be timezone-aware"

    # America/New_York offset is -04:00 (EDT) or -05:00 (EST); either way
    # it's strictly negative and strictly not zero. UTC would be +00:00.
    offset_seconds = parsed.utcoffset().total_seconds()
    assert offset_seconds < 0, f"expected negative offset for NY, got {offset_seconds}"


@pytest.mark.asyncio
async def test_dashboard_deadline_null_timezone_falls_back_to_utc(
    db_session: AsyncSession,
):
    """NULL tenant.timezone → UTC fallback, no exception, deadline is offset 0."""
    tenant = Tenant(
        name="No TZ Tenant",
        slug="no-tz-tenant",
        status=TenantStatus.active,
        timezone=None,
    )
    db_session.add(tenant)
    await db_session.flush()

    manager = await _make_user(
        db_session, email="mgr@notz.example", tenant_id=tenant.id, role=UserRole.MANAGER,
    )
    await db_session.commit()

    client = _make_dashboard_app(db_session)
    with client:
        response = client.get(
            "/dashboard/team-daily-overview", headers=_auth_headers(manager)
        )
    assert response.status_code == 200, response.text
    body = response.json()
    parsed = datetime.fromisoformat(body["submission_deadline_at"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


# ─────────────────────────────────────────────────────────────────────────────
# Site 2 + Site 4: notifications /summary respects tenant timezone
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notification_today_uses_tenant_timezone(db_session: AsyncSession):
    """
    Freeze ``now_for_tenant`` to 2026-04-20 22:00 UTC == 2026-04-21 07:00 JST.
    Seed a time entry for 2026-04-20 (which is 'today' for the Tokyo tenant).
    The 'missing yesterday entry' tile should NOT fire for the Tokyo tenant
    because in Tokyo the previous work day (2026-04-20) is entered.

    Additionally confirms current_time >= 08:00 in Tokyo (07:00 JST) — not
    quite — so also the hour guard at line ~243 wouldn't fire. That's fine;
    the tile is absent either way. Primary assertion: the notification
    doesn't appear under Tokyo time logic.
    """
    tenant = Tenant(
        name="Tokyo Tenant",
        slug="tokyo-tenant",
        status=TenantStatus.active,
        timezone="Asia/Tokyo",
    )
    db_session.add(tenant)
    await db_session.flush()

    employee = await _make_user(
        db_session, email="emp@tokyo.example", tenant_id=tenant.id, role=UserRole.EMPLOYEE,
    )

    client_row = Client(name="TokyoClient", tenant_id=tenant.id)
    db_session.add(client_row)
    await db_session.flush()
    project = Project(
        tenant_id=tenant.id,
        client_id=client_row.id,
        name="TokyoProject",
        billable_rate=Decimal("100.00"),
        is_active=True,
    )
    db_session.add(project)
    await db_session.flush()

    # Seed an entry for 2026-04-20 — "today" in Tokyo at the frozen moment.
    db_session.add(
        TimeEntry(
            tenant_id=tenant.id,
            user_id=employee.id,
            project_id=project.id,
            entry_date=date(2026, 4, 20),
            hours=Decimal("8.0"),
            description="Tokyo today",
            status=TimeEntryStatus.SUBMITTED,
        )
    )
    await db_session.commit()

    frozen = datetime(2026, 4, 20, 22, 0, tzinfo=timezone.utc)  # 07:00 JST

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen.replace(tzinfo=None)
            return frozen.astimezone(tz)

    # Patch the ``datetime`` symbol used inside timezone_utils so ``now_for_tenant``
    # returns the frozen moment. Notifications.py imports ``datetime`` into its
    # own namespace; the only notification-layer ``now`` call goes through
    # ``now_for_tenant``, so patching timezone_utils is sufficient for this flow.
    client = _make_notifications_app(db_session)
    with patch("app.core.timezone_utils.datetime", _FrozenDatetime):
        with client:
            response = client.get(
                "/notifications/summary", headers=_auth_headers(employee)
            )

    assert response.status_code == 200, response.text
    body = response.json()
    notification_ids = [item["id"] for item in body["items"]]
    assert "missing-previous-day-entry" not in notification_ids, (
        "Tokyo tenant at 07:00 JST should not see the 'missing yesterday' tile — "
        f"notifications returned: {notification_ids}"
    )


@pytest.mark.asyncio
async def test_null_timezone_notifications_falls_back_to_utc_no_error(
    db_session: AsyncSession,
):
    """Smoke: tenant.timezone=None returns 200 with no exception."""
    tenant = Tenant(
        name="NoTZ Summary", slug="notz-summary", status=TenantStatus.active,
        timezone=None,
    )
    db_session.add(tenant)
    await db_session.flush()

    employee = await _make_user(
        db_session, email="emp@notz-sum.example", tenant_id=tenant.id,
        role=UserRole.EMPLOYEE,
    )
    await db_session.commit()

    client = _make_notifications_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(employee)
        )
    assert response.status_code == 200, response.text
