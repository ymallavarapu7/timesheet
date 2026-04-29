"""
Regression tests for Fix 10 — PLATFORM_ADMIN must never receive employee- or
manager-scoped notification tiles. Batch 1's early-return at the top of
``_build_notification_summary`` (``if current_user.tenant_id is None: return
empty``) is the mechanism that delivers this. Fix 10 is verification-only: it
pins the behavior so future refactors cannot bypass the guard without
breaking a test.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - test shim
    return "JSON"


from app.api import notifications
from app.core.security import create_access_token, get_password_hash
from app.db import get_db
from app.core.deps import get_tenant_db
from app.models.assignments import EmployeeManagerAssignment
from app.models.base import Base
from app.models.client import Client
from app.models.project import Project
from app.models.tenant import Tenant, TenantStatus
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.time_off_request import TimeOffRequest, TimeOffStatus, TimeOffType
from app.models.user import User, UserRole


EMPLOYEE_TILE_IDS = {
    "rejected-time-entries",
    "draft-time-entries",
    "rejected-time-off",
    "draft-time-off",
    "missing-previous-day-entry",
    "weekly-timesheet-reminder",
}

APPROVER_TILE_IDS = {
    "pending-time-approvals",
    "pending-timeoff-approvals",
    "missing-team-yesterday-entries",
}


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "platformadmin_tiles.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


def _make_app(db_session: AsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(notifications.router)

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


async def _seed_tenant_with_everything(session: AsyncSession) -> dict:
    """Seed entries/requests that would light up every tile if the filter leaked."""
    tenant = Tenant(name="Tenant A", slug="tenant-a", status=TenantStatus.active)
    session.add(tenant)
    await session.flush()

    client = Client(name="Client A", tenant_id=tenant.id)
    session.add(client)
    await session.flush()

    project = Project(
        tenant_id=tenant.id,
        client_id=client.id,
        name="Project A",
        billable_rate=Decimal("100.00"),
        is_active=True,
    )
    session.add(project)
    await session.flush()

    emp = await _make_user(
        session, email="emp@a.example", tenant_id=tenant.id, role=UserRole.EMPLOYEE
    )
    mgr = await _make_user(
        session, email="mgr@a.example", tenant_id=tenant.id, role=UserRole.MANAGER
    )
    session.add(EmployeeManagerAssignment(employee_id=emp.id, manager_id=mgr.id))
    await session.flush()

    today = date.today()
    for status_, day_offset in [
        (TimeEntryStatus.REJECTED, 0),
        (TimeEntryStatus.DRAFT, 1),
        (TimeEntryStatus.SUBMITTED, 2),
    ]:
        session.add(
            TimeEntry(
                tenant_id=tenant.id,
                user_id=emp.id,
                project_id=project.id,
                entry_date=today - timedelta(days=day_offset),
                hours=Decimal("8.00"),
                description="entry",
                status=status_,
            )
        )
    for status_, day_offset in [
        (TimeOffStatus.REJECTED, 0),
        (TimeOffStatus.DRAFT, 1),
        (TimeOffStatus.SUBMITTED, 2),
    ]:
        session.add(
            TimeOffRequest(
                tenant_id=tenant.id,
                user_id=emp.id,
                request_date=today - timedelta(days=day_offset),
                hours=Decimal("8.00"),
                leave_type=TimeOffType.PTO,
                reason="Vacation",
                status=status_,
            )
        )
    return {"tenant": tenant, "project": project, "emp": emp, "mgr": mgr}


def _tile_ids(body: dict) -> set:
    return {item["id"] for item in body.get("items", [])}


def _count_for(body: dict, tile_id: str) -> int:
    for item in body.get("items", []):
        if item["id"] == tile_id:
            return int(item["count"])
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# PLATFORM_ADMIN — every tile must be suppressed
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_platform_admin_sees_no_employee_centric_tiles(db_session: AsyncSession):
    await _seed_tenant_with_everything(db_session)
    pa = await _make_user(
        db_session,
        email="platformadmin@platform.example",
        tenant_id=None,
        role=UserRole.PLATFORM_ADMIN,
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(pa)
        )

    assert response.status_code == 200
    body = response.json()
    assert EMPLOYEE_TILE_IDS.isdisjoint(_tile_ids(body))
    assert body["total_count"] == 0


@pytest.mark.asyncio
async def test_platform_admin_sees_no_manager_tiles(db_session: AsyncSession):
    await _seed_tenant_with_everything(db_session)
    pa = await _make_user(
        db_session,
        email="platformadmin@platform.example",
        tenant_id=None,
        role=UserRole.PLATFORM_ADMIN,
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(pa)
        )

    assert response.status_code == 200
    body = response.json()
    assert APPROVER_TILE_IDS.isdisjoint(_tile_ids(body))
    assert body["total_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# EMPLOYEE baseline — confirm Fix 10 didn't nuke legitimate employee tiles
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regular_employee_still_sees_own_tiles(db_session: AsyncSession):
    seed = await _seed_tenant_with_everything(db_session)
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(seed["emp"])
        )

    assert response.status_code == 200
    body = response.json()
    tile_ids = _tile_ids(body)
    assert "rejected-time-entries" in tile_ids
    assert _count_for(body, "rejected-time-entries") >= 1
    assert "draft-time-entries" in tile_ids
    assert _count_for(body, "draft-time-entries") >= 1
