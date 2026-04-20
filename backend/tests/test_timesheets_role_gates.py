"""
Regression tests for Fix 8 — the create-time-entry role gate in
``timesheets.py`` previously omitted SENIOR_MANAGER and CEO, returning 403
for users the frontend lets navigate there. The fix adds both roles to the
allow-list.
"""
from datetime import date
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


from app.api import timesheets as timesheets_api
from app.core.security import create_access_token, get_password_hash
from app.db import get_db
from app.models.base import Base
from app.models.client import Client
from app.models.project import Project
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "ts_role_gate.db"
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
    app.include_router(timesheets_api.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
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
    tenant_id: int,
    role: UserRole,
) -> User:
    user = User(
        tenant_id=tenant_id,
        email=email,
        username=email.split("@")[0].replace(".", "-"),
        full_name=email,
        title="Engineer",
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
async def tenant_with_project(db_session: AsyncSession) -> dict:
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
    await db_session.commit()

    return {"tenant": tenant, "project": project}


def _create_payload(project_id: int) -> dict:
    return {
        "project_id": project_id,
        "entry_date": date.today().isoformat(),
        "hours": "8.00",
        "description": "Role-gate regression test entry",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fix 8
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ceo_can_access_previously_gated_endpoint(
    db_session: AsyncSession, tenant_with_project: dict
):
    tenant = tenant_with_project["tenant"]
    project = tenant_with_project["project"]
    ceo = await _make_user(
        db_session, email="ceo@a.example", tenant_id=tenant.id, role=UserRole.CEO
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.post(
            "/timesheets",
            headers=_auth_headers(ceo),
            json=_create_payload(project.id),
        )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_senior_manager_can_access_previously_gated_endpoint(
    db_session: AsyncSession, tenant_with_project: dict
):
    tenant = tenant_with_project["tenant"]
    project = tenant_with_project["project"]
    senior = await _make_user(
        db_session, email="senior@a.example", tenant_id=tenant.id, role=UserRole.SENIOR_MANAGER
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.post(
            "/timesheets",
            headers=_auth_headers(senior),
            json=_create_payload(project.id),
        )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_manager_can_still_access_endpoint(
    db_session: AsyncSession, tenant_with_project: dict
):
    tenant = tenant_with_project["tenant"]
    project = tenant_with_project["project"]
    manager = await _make_user(
        db_session, email="manager@a.example", tenant_id=tenant.id, role=UserRole.MANAGER
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.post(
            "/timesheets",
            headers=_auth_headers(manager),
            json=_create_payload(project.id),
        )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_employee_role_still_gated_appropriately(
    db_session: AsyncSession, tenant_with_project: dict
):
    """EMPLOYEE was already in the allow-list pre-fix; post-fix they still
    reach the create path. The only observable change is that the role gate
    does not 403 them — downstream (project access, etc.) may still succeed
    or fail on its own merits."""
    tenant = tenant_with_project["tenant"]
    project = tenant_with_project["project"]
    emp = await _make_user(
        db_session, email="emp@a.example", tenant_id=tenant.id, role=UserRole.EMPLOYEE
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.post(
            "/timesheets",
            headers=_auth_headers(emp),
            json=_create_payload(project.id),
        )
    # Whatever the outcome, it must not be the role-gate 403 we were fixing.
    assert response.status_code == 201, response.text
