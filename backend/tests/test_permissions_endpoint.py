from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app import models  # noqa: F401
from app.api import auth, users
from app.core.security import get_password_hash
from app.db import get_db
from app.core.deps import get_tenant_db
from app.models.base import Base
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole
from app.seed_permissions import seed_async


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - shim
    return "JSON"


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    with TemporaryDirectory(dir=REPO_ROOT) as temp_dir:
        db_path = Path(temp_dir) / "permissions_endpoint.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            yield session

        await engine.dispose()


@pytest_asyncio.fixture
async def seeded_users(db_session: AsyncSession) -> dict[str, User]:
    tenant = Tenant(name="Endpoint Tenant", slug="endpoint-tenant", status=TenantStatus.active)
    employee = User(
        tenant=tenant,
        email="employee@endpoint.test",
        username="employee-endpoint",
        full_name="Endpoint Employee",
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        email_verified=True,
        is_active=True,
        created_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
    )
    admin = User(
        tenant=tenant,
        email="admin@endpoint.test",
        username="admin-endpoint",
        full_name="Endpoint Admin",
        hashed_password=get_password_hash("password"),
        role=UserRole.ADMIN,
        email_verified=True,
        is_active=True,
        created_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
    )
    platform_admin = User(
        email="platform@endpoint.test",
        username="platform-endpoint",
        full_name="Endpoint Platform Admin",
        hashed_password=get_password_hash("password"),
        role=UserRole.PLATFORM_ADMIN,
        email_verified=True,
        is_active=True,
        created_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
    )
    db_session.add_all([tenant, employee, admin, platform_admin])
    await db_session.commit()

    await seed_async(db_session)
    await db_session.commit()

    return {
        "employee": employee,
        "admin": admin,
        "platform_admin": platform_admin,
    }


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession, seeded_users: dict[str, User]):
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(users.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_get_db
    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def _login(api_client: TestClient, email: str) -> dict[str, str]:
    response = api_client.post(
        "/auth/login",
        json={"email": email, "password": "password"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_get_my_permissions_returns_list_for_employee(api_client: TestClient):
    response = api_client.get(
        "/users/me/permissions",
        headers=_login(api_client, "employee@endpoint.test"),
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["permissions"], list)
    assert "time_entry.read_own" in body["permissions"]
    assert "audit.read" not in body["permissions"]


def test_get_my_permissions_returns_list_for_admin(api_client: TestClient):
    response = api_client.get(
        "/users/me/permissions",
        headers=_login(api_client, "admin@endpoint.test"),
    )

    assert response.status_code == 200
    permissions = response.json()["permissions"]
    assert "audit.read" in permissions
    assert "tenant.create" not in permissions


def test_get_my_permissions_returns_list_for_platform_admin(api_client: TestClient):
    response = api_client.get(
        "/users/me/permissions",
        headers=_login(api_client, "platform@endpoint.test"),
    )

    assert response.status_code == 200
    permissions = response.json()["permissions"]
    assert "tenant.create" in permissions
    assert "platform.admin.access" in permissions


def test_get_my_permissions_requires_authentication(api_client: TestClient):
    response = api_client.get("/users/me/permissions")

    assert response.status_code in {401, 403}
