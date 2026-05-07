"""
Regression tests for Fix 9 — ``/dashboard/team-daily-overview`` returns 403
for roles that do not have a team (EMPLOYEE, PLATFORM_ADMIN). Previously the
endpoint returned a well-formed zero response, which misrepresented the
resource as existing-but-empty. Authorized roles (MANAGER,
CEO, ADMIN) continue to receive 200.
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


from app.api import dashboard as dashboard_api
from app.core.security import create_access_token, get_password_hash
from app.db import get_db
from app.core.deps import get_tenant_db
from app.models.base import Base
from app.models.client import Client
from app.models.project import Project
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "team_overview_access.db"
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
    app.include_router(dashboard_api.router)

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


@pytest_asyncio.fixture
async def tenant_and_project(db_session: AsyncSession) -> dict:
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


# ─────────────────────────────────────────────────────────────────────────────
# 403 for unauthorized roles
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_employee_gets_403_on_team_daily_overview(
    db_session: AsyncSession, tenant_and_project: dict
):
    emp = await _make_user(
        db_session, email="emp@a.example", tenant_id=tenant_and_project["tenant"].id,
        role=UserRole.EMPLOYEE,
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/dashboard/team-daily-overview", headers=_auth_headers(emp)
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_platform_admin_gets_403_on_team_daily_overview(db_session: AsyncSession):
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
            "/dashboard/team-daily-overview", headers=_auth_headers(pa)
        )
    assert response.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# 200 for authorized roles
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_manager_gets_200_on_team_daily_overview(
    db_session: AsyncSession, tenant_and_project: dict
):
    mgr = await _make_user(
        db_session, email="manager@a.example",
        tenant_id=tenant_and_project["tenant"].id, role=UserRole.MANAGER,
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/dashboard/team-daily-overview", headers=_auth_headers(mgr)
        )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_senior_manager_gets_200_on_team_daily_overview(
    db_session: AsyncSession, tenant_and_project: dict
):
    senior = await _make_user(
        db_session, email="senior@a.example",
        tenant_id=tenant_and_project["tenant"].id, role=UserRole.MANAGER,
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/dashboard/team-daily-overview", headers=_auth_headers(senior)
        )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_ceo_gets_200_on_team_daily_overview(
    db_session: AsyncSession, tenant_and_project: dict
):
    ceo = await _make_user(
        db_session, email="ceo@a.example",
        tenant_id=tenant_and_project["tenant"].id, role=UserRole.VIEWER,
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/dashboard/team-daily-overview", headers=_auth_headers(ceo)
        )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_admin_gets_200_on_team_daily_overview(
    db_session: AsyncSession, tenant_and_project: dict
):
    admin = await _make_user(
        db_session, email="admin@a.example",
        tenant_id=tenant_and_project["tenant"].id, role=UserRole.ADMIN,
    )
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.get(
            "/dashboard/team-daily-overview", headers=_auth_headers(admin)
        )
    assert response.status_code == 200, response.text
