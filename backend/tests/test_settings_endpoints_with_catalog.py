"""
End-to-end tests for the tenant settings endpoints after they were rewired
to use the ``setting_definitions`` catalog and the typed accessor.

Covers:
  * GET returns catalog defaults for unset keys (additive response shape);
  * GET catalog returns the full metadata list;
  * PATCH validates and rejects bad values/unknown keys with 422;
  * PATCH accepts valid values, logs a TENANT_SETTING_CHANGED activity row,
    and the value round-trips on a subsequent GET;
  * public endpoint returns only public keys for a non-admin user.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
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


from app.api import users as users_api
from app.core.security import create_access_token, get_password_hash
from app.db import get_db
from app.models.activity_log import ActivityLog
from app.models.base import Base
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole
from app.seed_setting_definitions import seed_async


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'settings_endpoints.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        await seed_async(session)
        await session.commit()
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def seed_users(db_session: AsyncSession) -> dict:
    tenant = Tenant(name="Tenant A", slug="tenant-a", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.flush()

    admin = User(
        tenant_id=tenant.id,
        email="admin@a.example",
        username="admin-a",
        full_name="Admin A",
        hashed_password=get_password_hash("password"),
        role=UserRole.ADMIN,
        is_active=True,
        email_verified=True,
        has_changed_password=True,
    )
    emp = User(
        tenant_id=tenant.id,
        email="emp@a.example",
        username="emp-a",
        full_name="Emp A",
        title="Engineer",
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        is_active=True,
        email_verified=True,
        has_changed_password=True,
    )
    db_session.add_all([admin, emp])
    await db_session.commit()
    return {"tenant": tenant, "admin": admin, "emp": emp}


def _make_app(db_session: AsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(users_api.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _auth(user: User) -> dict:
    token = create_access_token(
        {"sub": str(user.id), "tenant_id": user.tenant_id}
    )
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────────────────────
# GET /users/tenant-settings
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_all_settings_includes_catalog_defaults(
    db_session: AsyncSession, seed_users: dict
):
    client = _make_app(db_session)
    with client:
        resp = client.get(
            "/users/tenant-settings", headers=_auth(seed_users["admin"])
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["max_hours_per_day"] == 12.0
    assert body["week_start_day"] == 0
    assert body["allow_partial_week_submit"] is False
    # Every catalog category represented.
    for key in [
        "time_entry_past_days",
        "time_off_future_days",
        "max_failed_login_attempts",
        "notification_ttl_days",
        "smtp_host",
    ]:
        assert key in body


@pytest.mark.asyncio
async def test_get_catalog_returns_metadata(
    db_session: AsyncSession, seed_users: dict
):
    client = _make_app(db_session)
    with client:
        resp = client.get(
            "/users/tenant-settings/catalog", headers=_auth(seed_users["admin"])
        )
    assert resp.status_code == 200, resp.text
    catalog = resp.json()
    assert isinstance(catalog, list)
    assert len(catalog) >= 30
    sample = next(c for c in catalog if c["key"] == "max_hours_per_day")
    assert sample["data_type"] == "float"
    assert sample["category"] == "time_entry"
    assert sample["validation"]["min"] == 0.5
    assert sample["validation"]["max"] == 24
    assert sample["is_public"] is True


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /users/tenant-settings
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_settings_validates_and_rejects_bad_value(
    db_session: AsyncSession, seed_users: dict
):
    client = _make_app(db_session)
    with client:
        resp = client.patch(
            "/users/tenant-settings",
            headers=_auth(seed_users["admin"]),
            json={"max_hours_per_day": "banana"},
        )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_settings_accepts_valid_value_and_logs(
    db_session: AsyncSession, seed_users: dict
):
    client = _make_app(db_session)
    with client:
        patch = client.patch(
            "/users/tenant-settings",
            headers=_auth(seed_users["admin"]),
            json={"max_hours_per_day": 10},
        )
        assert patch.status_code == 200, patch.text

        get = client.get(
            "/users/tenant-settings", headers=_auth(seed_users["admin"])
        )
        assert get.json()["max_hours_per_day"] == 10.0

    log = await db_session.execute(
        select(ActivityLog).where(
            ActivityLog.activity_type == "TENANT_SETTING_CHANGED"
        )
    )
    entries = list(log.scalars().all())
    assert len(entries) == 1
    assert entries[0].metadata_json["key"] == "max_hours_per_day"
    assert entries[0].metadata_json["after"] == 10.0


@pytest.mark.asyncio
async def test_patch_settings_rejects_unknown_key(
    db_session: AsyncSession, seed_users: dict
):
    client = _make_app(db_session)
    with client:
        resp = client.patch(
            "/users/tenant-settings",
            headers=_auth(seed_users["admin"]),
            json={"nonexistent_key": "value"},
        )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_settings_rejects_min_max_violations(
    db_session: AsyncSession, seed_users: dict
):
    client = _make_app(db_session)
    with client:
        too_small = client.patch(
            "/users/tenant-settings",
            headers=_auth(seed_users["admin"]),
            json={"max_hours_per_day": -1},
        )
        too_big = client.patch(
            "/users/tenant-settings",
            headers=_auth(seed_users["admin"]),
            json={"max_hours_per_day": 999},
        )
        bad_enum = client.patch(
            "/users/tenant-settings",
            headers=_auth(seed_users["admin"]),
            json={"week_start_day": 5},
        )
    assert too_small.status_code == 422
    assert too_big.status_code == 422
    assert bad_enum.status_code == 422


@pytest.mark.asyncio
async def test_patch_settings_non_admin_is_forbidden(
    db_session: AsyncSession, seed_users: dict
):
    client = _make_app(db_session)
    with client:
        resp = client.patch(
            "/users/tenant-settings",
            headers=_auth(seed_users["emp"]),
            json={"max_hours_per_day": 8},
        )
    assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# GET /users/tenant-settings/public
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_public_settings_returns_subset(
    db_session: AsyncSession, seed_users: dict
):
    client = _make_app(db_session)
    with client:
        resp = client.get(
            "/users/tenant-settings/public", headers=_auth(seed_users["emp"])
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "week_start_day" in body
    # is_public=False keys MUST NOT leak via the public endpoint.
    assert "smtp_password" not in body
    assert "max_failed_login_attempts" not in body
