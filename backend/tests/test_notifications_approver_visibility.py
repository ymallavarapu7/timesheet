"""
Regression tests for Fix 6 — pending-approvals tile visibility.

Batch 1 already routes CEO/ADMIN through the ``tenant_wide_roles`` branch of
``_build_notification_summary`` so the counts are computed correctly. These
tests verify that:

  * the ``pending-time-approvals`` and ``pending-timeoff-approvals`` tiles
    are actually emitted for CEO and ADMIN (not just MANAGER/SENIOR_MANAGER),
  * EMPLOYEE users do not see them,
  * the ``missing-team-yesterday-entries`` tile stays gated to scoped roles
    (MANAGER/SENIOR_MANAGER) only — the Batch 1 bonus restriction.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from unittest.mock import patch


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


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "approver_visibility.db"
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
        username=email.split("@")[0],
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


@pytest_asyncio.fixture
async def tenant_with_pending(db_session: AsyncSession) -> dict:
    """Tenant with a MANAGER, direct report, a CEO, an ADMIN, one submitted
    TimeEntry, and one submitted TimeOffRequest — enough rows to light up
    both pending-approval tiles under every approver role."""
    tenant = Tenant(name="Tenant A", slug="tenant-a", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.flush()

    client = Client(name="Client A", tenant_id=tenant.id)
    db_session.add(client)
    await db_session.flush()

    project = Project(
        tenant_id=tenant.id,
        client_id=client.id,
        name="Project A",
        billable_rate=Decimal("100.00"),
        is_active=True,
    )
    db_session.add(project)
    await db_session.flush()

    ceo = await _make_user(db_session, email="ceo@a.example", tenant_id=tenant.id, role=UserRole.CEO)
    admin = await _make_user(db_session, email="admin@a.example", tenant_id=tenant.id, role=UserRole.ADMIN)
    manager = await _make_user(db_session, email="manager@a.example", tenant_id=tenant.id, role=UserRole.MANAGER)
    senior = await _make_user(db_session, email="senior@a.example", tenant_id=tenant.id, role=UserRole.SENIOR_MANAGER)
    employee = await _make_user(db_session, email="emp@a.example", tenant_id=tenant.id, role=UserRole.EMPLOYEE)

    # Give the senior manager their own direct report so they, too, can approve.
    senior_report = await _make_user(
        db_session, email="senior-emp@a.example", tenant_id=tenant.id, role=UserRole.EMPLOYEE
    )

    db_session.add_all([
        EmployeeManagerAssignment(employee_id=employee.id, manager_id=manager.id),
        EmployeeManagerAssignment(employee_id=senior_report.id, manager_id=senior.id),
    ])
    await db_session.flush()

    today = date.today()
    for submitter in (employee, senior_report):
        db_session.add(
            TimeEntry(
                tenant_id=tenant.id,
                user_id=submitter.id,
                project_id=project.id,
                entry_date=today,
                hours=Decimal("8.00"),
                description="pending",
                status=TimeEntryStatus.SUBMITTED,
            )
        )
        db_session.add(
            TimeOffRequest(
                tenant_id=tenant.id,
                user_id=submitter.id,
                request_date=today,
                hours=Decimal("8.00"),
                leave_type=TimeOffType.PTO,
                reason="Vacation",
                status=TimeOffStatus.SUBMITTED,
            )
        )
    await db_session.commit()

    return {
        "tenant": tenant,
        "ceo": ceo,
        "admin": admin,
        "manager": manager,
        "senior": senior,
        "employee": employee,
        "project": project,
    }


def _tile_ids(body: dict) -> set:
    return {item["id"] for item in body.get("items", [])}


def _tile_count(body: dict, tile_id: str) -> int:
    for item in body.get("items", []):
        if item["id"] == tile_id:
            return int(item["count"])
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# pending-time-approvals tile
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ceo_sees_pending_time_approvals_tile(
    db_session: AsyncSession, tenant_with_pending: dict
):
    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(tenant_with_pending["ceo"])
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "pending-time-approvals" in _tile_ids(body)
    assert _tile_count(body, "pending-time-approvals") >= 1


@pytest.mark.asyncio
async def test_admin_sees_pending_time_approvals_tile(
    db_session: AsyncSession, tenant_with_pending: dict
):
    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(tenant_with_pending["admin"])
        )
    assert response.status_code == 200
    body = response.json()
    assert "pending-time-approvals" in _tile_ids(body)
    assert _tile_count(body, "pending-time-approvals") >= 1


@pytest.mark.asyncio
async def test_manager_sees_pending_time_approvals_tile(
    db_session: AsyncSession, tenant_with_pending: dict
):
    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(tenant_with_pending["manager"])
        )
    assert response.status_code == 200
    body = response.json()
    assert "pending-time-approvals" in _tile_ids(body)
    assert _tile_count(body, "pending-time-approvals") >= 1


@pytest.mark.asyncio
async def test_senior_manager_sees_pending_time_approvals_tile(
    db_session: AsyncSession, tenant_with_pending: dict
):
    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(tenant_with_pending["senior"])
        )
    assert response.status_code == 200
    body = response.json()
    assert "pending-time-approvals" in _tile_ids(body)
    assert _tile_count(body, "pending-time-approvals") >= 1


@pytest.mark.asyncio
async def test_employee_does_not_see_pending_time_approvals_tile(
    db_session: AsyncSession, tenant_with_pending: dict
):
    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(tenant_with_pending["employee"])
        )
    assert response.status_code == 200
    body = response.json()
    assert "pending-time-approvals" not in _tile_ids(body)
    assert "pending-timeoff-approvals" not in _tile_ids(body)


# ─────────────────────────────────────────────────────────────────────────────
# pending-timeoff-approvals tile
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ceo_sees_pending_timeoff_approvals_tile(
    db_session: AsyncSession, tenant_with_pending: dict
):
    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(tenant_with_pending["ceo"])
        )
    assert response.status_code == 200
    body = response.json()
    assert "pending-timeoff-approvals" in _tile_ids(body)
    assert _tile_count(body, "pending-timeoff-approvals") >= 1


@pytest.mark.asyncio
async def test_admin_sees_pending_timeoff_approvals_tile(
    db_session: AsyncSession, tenant_with_pending: dict
):
    client = _make_app(db_session)
    with client:
        response = client.get(
            "/notifications/summary", headers=_auth_headers(tenant_with_pending["admin"])
        )
    assert response.status_code == 200
    body = response.json()
    assert "pending-timeoff-approvals" in _tile_ids(body)
    assert _tile_count(body, "pending-timeoff-approvals") >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Bonus-from-Batch-1 — missing-team-yesterday-entries stays scoped-roles-only
# ─────────────────────────────────────────────────────────────────────────────


class _AfternoonDatetime(datetime):
    """Force notifications.py to see a ``now`` after 14:00 UTC, so the
    missing-team tile's time guard is active."""

    _frozen: datetime = datetime(2026, 4, 17, 15, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if tz is None:
            return cls._frozen.replace(tzinfo=None)
        return cls._frozen.astimezone(tz)


def _patch_afternoon():
    return patch.object(notifications, "datetime", _AfternoonDatetime)


@pytest.mark.asyncio
async def test_missing_team_entries_tile_still_scoped_roles_only(
    db_session: AsyncSession, tenant_with_pending: dict
):
    client = _make_app(db_session)
    with client, _patch_afternoon():
        ceo_resp = client.get(
            "/notifications/summary", headers=_auth_headers(tenant_with_pending["ceo"])
        )
        admin_resp = client.get(
            "/notifications/summary", headers=_auth_headers(tenant_with_pending["admin"])
        )
        manager_resp = client.get(
            "/notifications/summary", headers=_auth_headers(tenant_with_pending["manager"])
        )

    assert ceo_resp.status_code == 200
    assert admin_resp.status_code == 200
    assert manager_resp.status_code == 200

    assert "missing-team-yesterday-entries" not in _tile_ids(ceo_resp.json())
    assert "missing-team-yesterday-entries" not in _tile_ids(admin_resp.json())
    # The manager has a direct report, so the scoped tile should appear.
    assert "missing-team-yesterday-entries" in _tile_ids(manager_resp.json())
