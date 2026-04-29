"""
Regression tests for the defense-in-depth tenant filter applied to per-user
notification tile queries (rejected entries, draft entries, weekly reminder,
etc.). Today `user_id` is globally unique so the tenant filter is redundant,
but the filter must be in the WHERE clause to protect against future changes
in `user_id` uniqueness, and it must also short-circuit for PLATFORM_ADMIN
(who has NULL tenant_id — without the guard the count query would return all
rows in the table).
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
from app.models.base import Base
from app.models.client import Client
from app.models.project import Project
from app.models.tenant import Tenant, TenantStatus
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "per_user_tenant.db"
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
    """Mint an access token directly; avoids slowapi rate-limiting on /auth/login."""
    token = create_access_token(
        {"sub": str(user.id), "tenant_id": user.tenant_id}
    )
    return {"Authorization": f"Bearer {token}"}


def _count_for(body: dict, notification_id: str) -> int:
    for item in body.get("items", []):
        if item["id"] == notification_id:
            return int(item["count"])
    return 0


@pytest.mark.asyncio
async def test_per_user_tile_excludes_entries_with_foreign_tenant(
    db_session: AsyncSession,
):
    """Insert a TimeEntry whose user_id matches the authenticated user but
    whose tenant_id points to a different tenant (simulates a future world
    where user_id is no longer globally unique, or a misrouted write). The
    rejected-entries tile must not count it.
    """
    tenant_a = Tenant(name="Tenant A", slug="tenant-a", status=TenantStatus.active)
    tenant_b = Tenant(name="Tenant B", slug="tenant-b", status=TenantStatus.active)
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()

    client_a = Client(name="Client A", tenant_id=tenant_a.id)
    client_b = Client(name="Client B", tenant_id=tenant_b.id)
    db_session.add_all([client_a, client_b])
    await db_session.flush()

    project_a = Project(
        tenant_id=tenant_a.id,
        client_id=client_a.id,
        name="Project A",
        billable_rate=Decimal("100.00"),
        is_active=True,
    )
    project_b = Project(
        tenant_id=tenant_b.id,
        client_id=client_b.id,
        name="Project B",
        billable_rate=Decimal("100.00"),
        is_active=True,
    )
    db_session.add_all([project_a, project_b])
    await db_session.flush()

    emp = User(
        tenant_id=tenant_a.id,
        email="emp@a.example",
        username="emp-a",
        full_name="Employee A",
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        is_active=True,
        has_changed_password=True,
        email_verified=True,
    )
    db_session.add(emp)
    await db_session.flush()

    today = date.today()
    # One legitimate rejected entry in the user's own tenant.
    db_session.add(
        TimeEntry(
            tenant_id=tenant_a.id,
            user_id=emp.id,
            project_id=project_a.id,
            entry_date=today,
            hours=Decimal("8.00"),
            description="ok",
            status=TimeEntryStatus.REJECTED,
        )
    )
    # Two rejected entries mis-tagged with tenant B. Must NOT be counted.
    for offset in (1, 2):
        db_session.add(
            TimeEntry(
                tenant_id=tenant_b.id,
                user_id=emp.id,
                project_id=project_b.id,
                entry_date=today - timedelta(days=offset),
                hours=Decimal("8.00"),
                description="foreign",
                status=TimeEntryStatus.REJECTED,
            )
        )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(emp)
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert _count_for(body, "rejected-time-entries") == 1


@pytest.mark.asyncio
async def test_platform_admin_per_user_tiles_empty(db_session: AsyncSession):
    """PLATFORM_ADMIN has tenant_id=None. Without the guard, per-user tile
    queries would see `tenant_id == NULL` which matches nothing in Postgres
    (but short-circuits to zero rows anyway). The fix treats PLATFORM_ADMIN
    as having no tenant-scoped notifications at all.
    """
    tenant_a = Tenant(name="Tenant A", slug="tenant-a", status=TenantStatus.active)
    db_session.add(tenant_a)
    await db_session.flush()

    client_a = Client(name="Client A", tenant_id=tenant_a.id)
    db_session.add(client_a)
    await db_session.flush()

    project_a = Project(
        tenant_id=tenant_a.id,
        client_id=client_a.id,
        name="Project A",
        billable_rate=Decimal("100.00"),
        is_active=True,
    )
    db_session.add(project_a)
    await db_session.flush()

    platform_admin = User(
        tenant_id=None,
        email="platformadmin@platform.example",
        username="platform-admin",
        full_name="Platform Admin",
        hashed_password=get_password_hash("password"),
        role=UserRole.PLATFORM_ADMIN,
        is_active=True,
        has_changed_password=True,
        email_verified=True,
    )
    db_session.add(platform_admin)
    await db_session.flush()

    # Plant rows that would light up every per-user tile if the guard leaked:
    # rejected entry, draft entry, nothing for the current week, etc.
    today = date.today()
    db_session.add(
        TimeEntry(
            tenant_id=tenant_a.id,
            user_id=platform_admin.id,  # would match if tenant filter were absent
            project_id=project_a.id,
            entry_date=today,
            hours=Decimal("8.00"),
            description="rejected",
            status=TimeEntryStatus.REJECTED,
        )
    )
    db_session.add(
        TimeEntry(
            tenant_id=tenant_a.id,
            user_id=platform_admin.id,
            project_id=project_a.id,
            entry_date=today - timedelta(days=1),
            hours=Decimal("8.00"),
            description="draft",
            status=TimeEntryStatus.DRAFT,
        )
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(platform_admin)
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_count"] == 0
    tile_ids = {item["id"] for item in body.get("items", [])}
    assert "rejected-time-entries" not in tile_ids
    assert "draft-time-entries" not in tile_ids
    assert "weekly-timesheet-reminder" not in tile_ids
    assert "missing-previous-day-entry" not in tile_ids
