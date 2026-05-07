"""
Regression tests for tenant isolation in /notifications/summary.

Covers the Fix 1 scenario: a MANAGER with zero direct reports must not see
pending-approval counts from other tenants, and the scoped/unscoped roles
must always apply a tenant filter to pending-approval queries.
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

# Map the Postgres-only JSONB type to JSON when compiled for SQLite so
# Base.metadata.create_all() works against the test database.
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - test shim
    return "JSON"


from app.api import auth, notifications
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


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "notif_tenant.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def two_tenants(db_session: AsyncSession) -> dict:
    """Two tenants, each with one project so time entries can reference it."""
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
    await db_session.commit()

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "project_a": project_a,
        "project_b": project_b,
    }


def _make_app(db_session: AsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(notifications.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_get_db
    return TestClient(app)


def _auth_headers(user: User) -> dict:
    """Mint an access token directly, bypassing /auth/login to avoid slowapi
    rate-limiting when many tests run in the same process."""
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
        username=email.split("@")[0],
        full_name=email,
        hashed_password=get_password_hash("password"),
        role=role,
        is_active=True,
        has_changed_password=True,
        email_verified=True,
    )
    session.add(user)
    await session.flush()
    return user


def _pending_time_count(body: dict) -> int:
    for item in body.get("items", []):
        if item["id"] == "pending-time-approvals":
            return int(item["count"])
    return 0


def _pending_time_off_count(body: dict) -> int:
    for item in body.get("items", []):
        if item["id"] == "pending-timeoff-approvals":
            return int(item["count"])
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_manager_with_zero_reports_sees_zero_pending_not_cross_tenant(
    db_session: AsyncSession, two_tenants: dict
):
    """MANAGER with no direct reports must not aggregate submitted entries
    from any other tenant — previously the empty list was coerced to None,
    dropping the user filter entirely.
    """
    tenant_a = two_tenants["tenant_a"]
    tenant_b = two_tenants["tenant_b"]
    project_b = two_tenants["project_b"]

    alice = await _make_user(
        db_session, email="alice.mgr@a.example", tenant_id=tenant_a.id, role=UserRole.MANAGER
    )
    bob = await _make_user(
        db_session, email="bob.emp@b.example", tenant_id=tenant_b.id, role=UserRole.EMPLOYEE
    )

    today = date.today()
    for offset in range(3):
        db_session.add(
            TimeEntry(
                tenant_id=tenant_b.id,
                user_id=bob.id,
                project_id=project_b.id,
                entry_date=today - timedelta(days=offset),
                hours=Decimal("8.00"),
                description="Cross-tenant entry",
                status=TimeEntryStatus.SUBMITTED,
            )
        )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(alice)
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert _pending_time_count(body) == 0
    # Make sure nothing mentions Bob's entries in the response payload at all.
    assert "bob.emp@b.example" not in response.text
    assert "Tenant B" not in response.text


@pytest.mark.asyncio
async def test_manager_with_reports_sees_only_own_tenant_pending(
    db_session: AsyncSession, two_tenants: dict
):
    tenant_a = two_tenants["tenant_a"]
    tenant_b = two_tenants["tenant_b"]
    project_a = two_tenants["project_a"]
    project_b = two_tenants["project_b"]

    alice = await _make_user(
        db_session, email="alice.mgr@a.example", tenant_id=tenant_a.id, role=UserRole.MANAGER
    )
    carol = await _make_user(
        db_session, email="carol.emp@a.example", tenant_id=tenant_a.id, role=UserRole.EMPLOYEE
    )
    bob = await _make_user(
        db_session, email="bob.emp@b.example", tenant_id=tenant_b.id, role=UserRole.EMPLOYEE
    )
    db_session.add(
        EmployeeManagerAssignment(employee_id=carol.id, manager_id=alice.id)
    )
    await db_session.flush()

    today = date.today()
    # 2 submitted entries for Carol in tenant A, counted as a single pending week
    # (pending_time_entries_count is distinct weeks, not rows).
    for offset in range(2):
        db_session.add(
            TimeEntry(
                tenant_id=tenant_a.id,
                user_id=carol.id,
                project_id=project_a.id,
                entry_date=today - timedelta(days=offset),
                hours=Decimal("8.00"),
                description="Tenant A entry",
                status=TimeEntryStatus.SUBMITTED,
            )
        )
    # 5 submitted entries for Bob in tenant B — MUST NOT appear.
    for offset in range(5):
        db_session.add(
            TimeEntry(
                tenant_id=tenant_b.id,
                user_id=bob.id,
                project_id=project_b.id,
                entry_date=today - timedelta(days=offset),
                hours=Decimal("8.00"),
                description="Tenant B entry",
                status=TimeEntryStatus.SUBMITTED,
            )
        )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(alice)
        )

    assert response.status_code == 200
    body = response.json()
    # 1 pending week for Carol (both entries land in same ISO week).
    assert _pending_time_count(body) == 1


@pytest.mark.asyncio
async def test_ceo_sees_all_tenant_pending_not_cross_tenant(
    db_session: AsyncSession, two_tenants: dict
):
    tenant_a = two_tenants["tenant_a"]
    tenant_b = two_tenants["tenant_b"]
    project_a = two_tenants["project_a"]
    project_b = two_tenants["project_b"]

    ceo = await _make_user(
        db_session, email="ceo@a.example", tenant_id=tenant_a.id, role=UserRole.VIEWER
    )
    mgr1 = await _make_user(
        db_session, email="m1@a.example", tenant_id=tenant_a.id, role=UserRole.EMPLOYEE
    )
    mgr2 = await _make_user(
        db_session, email="m2@a.example", tenant_id=tenant_a.id, role=UserRole.EMPLOYEE
    )
    bob = await _make_user(
        db_session, email="bob@b.example", tenant_id=tenant_b.id, role=UserRole.EMPLOYEE
    )

    today = date.today()
    # Tenant A: 4 entries, spread so that distinct (user, week) pairs == 4.
    # Two users × two distinct weeks each.
    for user in (mgr1, mgr2):
        for week_offset in (0, 7):
            db_session.add(
                TimeEntry(
                    tenant_id=tenant_a.id,
                    user_id=user.id,
                    project_id=project_a.id,
                    entry_date=today - timedelta(days=week_offset),
                    hours=Decimal("8.00"),
                    description="Tenant A entry",
                    status=TimeEntryStatus.SUBMITTED,
                )
            )
    # Tenant B: 7 entries — any leak would inflate the count.
    for offset in range(7):
        db_session.add(
            TimeEntry(
                tenant_id=tenant_b.id,
                user_id=bob.id,
                project_id=project_b.id,
                entry_date=today - timedelta(days=offset),
                hours=Decimal("8.00"),
                description="Tenant B entry",
                status=TimeEntryStatus.SUBMITTED,
            )
        )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(ceo)
        )

    assert response.status_code == 200
    body = response.json()
    assert _pending_time_count(body) == 4


@pytest.mark.asyncio
async def test_platform_admin_sees_no_tenant_scoped_tiles(
    db_session: AsyncSession, two_tenants: dict
):
    tenant_a = two_tenants["tenant_a"]
    project_a = two_tenants["project_a"]

    platform_admin = await _make_user(
        db_session,
        email="platformadmin@platform.example",
        tenant_id=None,
        role=UserRole.PLATFORM_ADMIN,
    )
    emp = await _make_user(
        db_session, email="emp@a.example", tenant_id=tenant_a.id, role=UserRole.EMPLOYEE
    )
    db_session.add(
        TimeEntry(
            tenant_id=tenant_a.id,
            user_id=emp.id,
            project_id=project_a.id,
            entry_date=date.today(),
            hours=Decimal("8.00"),
            description="entry",
            status=TimeEntryStatus.SUBMITTED,
        )
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(platform_admin)
        )

    assert response.status_code == 200
    body = response.json()
    # No tenant-scoped tiles should be present, and no cross-tenant counts leak.
    tile_ids = {item["id"] for item in body.get("items", [])}
    assert "pending-time-approvals" not in tile_ids
    assert "pending-timeoff-approvals" not in tile_ids
    assert body["total_count"] == 0


@pytest.mark.asyncio
async def test_time_off_equivalent(db_session: AsyncSession, two_tenants: dict):
    """Same 'manager with zero reports' scenario for time-off pending counts."""
    tenant_a = two_tenants["tenant_a"]
    tenant_b = two_tenants["tenant_b"]

    alice = await _make_user(
        db_session, email="alice.mgr@a.example", tenant_id=tenant_a.id, role=UserRole.MANAGER
    )
    bob = await _make_user(
        db_session, email="bob@b.example", tenant_id=tenant_b.id, role=UserRole.EMPLOYEE
    )

    today = date.today()
    for offset in range(3):
        db_session.add(
            TimeOffRequest(
                tenant_id=tenant_b.id,
                user_id=bob.id,
                request_date=today - timedelta(days=offset),
                hours=Decimal("8.00"),
                leave_type=TimeOffType.PTO,
                reason="Vacation",
                status=TimeOffStatus.SUBMITTED,
            )
        )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(alice)
        )

    assert response.status_code == 200
    body = response.json()
    assert _pending_time_off_count(body) == 0
