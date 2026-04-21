"""
Tests for the ``tenants.timezone`` column added in migration 029 and for the
``PATCH /tenants/{id}`` endpoint accepting a timezone value.

Uses the standard SQLite+JSONB-shim test pattern.
"""
from __future__ import annotations

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


from app.api import auth, tenants, users
from app.core.security import get_password_hash
from app.db import get_db
from app.models.base import Base
from app.models.setting_definition import SettingDefinition  # noqa: F401
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "tenant_tz.db"
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
async def api_client(db_session: AsyncSession):
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(tenants.router)
    app.include_router(users.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def platform_admin_headers(db_session: AsyncSession, api_client: TestClient) -> dict:
    platform_admin = User(
        tenant_id=None,
        email="platform@example.com",
        username="platform",
        full_name="Platform Admin",
        hashed_password=get_password_hash("password"),
        role=UserRole.PLATFORM_ADMIN,
        is_active=True,
    )
    db_session.add(platform_admin)
    await db_session.commit()
    login = api_client.post(
        "/auth/login",
        json={"email": "platform@example.com", "password": "password"},
    )
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────────────────────
# Model-level tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_model_has_timezone_field(db_session: AsyncSession):
    tenant = Tenant(
        name="ChiTown",
        slug="chitown",
        status=TenantStatus.active,
        timezone="America/Chicago",
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)

    # Reload cleanly to confirm round-trip.
    db_session.expire(tenant)
    refreshed = await db_session.get(Tenant, tenant.id)
    assert refreshed is not None
    assert refreshed.timezone == "America/Chicago"


@pytest.mark.asyncio
async def test_tenant_timezone_defaults_to_null(db_session: AsyncSession):
    tenant = Tenant(name="Nullzone", slug="nullzone", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    assert tenant.timezone is None


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint test: PATCH /tenants/{id} accepts and persists timezone
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_patch_accepts_timezone(
    db_session: AsyncSession,
    api_client: TestClient,
    platform_admin_headers: dict,
):
    tenant = Tenant(name="London Office", slug="london-office", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)

    response = api_client.patch(
        f"/tenants/{tenant.id}",
        json={"timezone": "Europe/London"},
        headers=platform_admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == "Europe/London"

    # Reload from DB and confirm persistence.
    db_session.expire(tenant)
    refreshed = await db_session.get(Tenant, tenant.id)
    assert refreshed is not None
    assert refreshed.timezone == "Europe/London"
