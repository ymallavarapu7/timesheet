"""
Regression tests for Fix 7 — verification email must not be queued or resent
for inactive users.

Covers the user-creation path (``POST /users``) and the
resend-verification path (``POST /users/{id}/resend-verification``).
"""
from unittest.mock import AsyncMock, patch

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


from app.api import users as users_api
from app.core.security import create_access_token, get_password_hash
from app.db import get_db
from app.core.deps import get_tenant_db
from app.models.base import Base
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "verification_gating.db"
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
    app.include_router(users_api.router)

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


@pytest_asyncio.fixture
async def tenant_and_admin(db_session: AsyncSession) -> dict:
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
    db_session.add(admin)
    await db_session.commit()
    return {"tenant": tenant, "admin": admin}


def _create_payload(email: str, *, is_active: bool) -> dict:
    return {
        "email": email,
        "username": email.split("@")[0].replace(".", "-"),
        "full_name": email,
        "title": "Engineer",
        "role": "EMPLOYEE",
        "is_active": is_active,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Creation path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verification_email_not_queued_for_inactive_user_at_creation(
    db_session: AsyncSession, tenant_and_admin: dict
):
    client = _make_app(db_session)
    sender = AsyncMock()
    with client, patch(
        "app.services.email_verification.send_verification_email", sender
    ), patch(
        "app.api.platform_settings.get_effective_smtp_config",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.tenant_email_service._get_active_oauth_mailbox",
        new=AsyncMock(return_value=None),
    ):
        response = client.post(
            "/users",
            headers=_auth_headers(tenant_and_admin["admin"]),
            json=_create_payload("inactive@a.example", is_active=False),
        )

    assert response.status_code == 201, response.text
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_verification_email_queued_for_active_user_at_creation(
    db_session: AsyncSession, tenant_and_admin: dict
):
    client = _make_app(db_session)
    sender = AsyncMock()
    with client, patch(
        "app.services.email_verification.send_verification_email", sender
    ), patch(
        "app.api.platform_settings.get_effective_smtp_config",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.tenant_email_service._get_active_oauth_mailbox",
        new=AsyncMock(return_value=None),
    ):
        response = client.post(
            "/users",
            headers=_auth_headers(tenant_and_admin["admin"]),
            json=_create_payload("active@a.example", is_active=True),
        )

    assert response.status_code == 201, response.text
    sender.assert_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# Resend path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resend_verification_rejects_inactive_user(
    db_session: AsyncSession, tenant_and_admin: dict
):
    tenant = tenant_and_admin["tenant"]
    inactive = User(
        tenant_id=tenant.id,
        email="inactive@a.example",
        username="inactive-a",
        full_name="Inactive",
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        is_active=False,
        email_verified=False,
        has_changed_password=False,
    )
    db_session.add(inactive)
    await db_session.commit()

    client = _make_app(db_session)
    sender = AsyncMock()
    with client, patch(
        "app.services.email_verification.send_verification_email", sender
    ):
        response = client.post(
            f"/users/{inactive.id}/resend-verification",
            headers=_auth_headers(tenant_and_admin["admin"]),
        )

    assert response.status_code == 400
    assert "inactive" in response.json()["detail"].lower()
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_resend_verification_rejects_already_verified_user(
    db_session: AsyncSession, tenant_and_admin: dict
):
    tenant = tenant_and_admin["tenant"]
    verified = User(
        tenant_id=tenant.id,
        email="verified@a.example",
        username="verified-a",
        full_name="Verified",
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        is_active=True,
        email_verified=True,
        has_changed_password=True,
    )
    db_session.add(verified)
    await db_session.commit()

    client = _make_app(db_session)
    sender = AsyncMock()
    with client, patch(
        "app.services.email_verification.send_verification_email", sender
    ):
        response = client.post(
            f"/users/{verified.id}/resend-verification",
            headers=_auth_headers(tenant_and_admin["admin"]),
        )

    assert response.status_code == 400
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_resend_verification_succeeds_for_active_unverified_user(
    db_session: AsyncSession, tenant_and_admin: dict
):
    tenant = tenant_and_admin["tenant"]
    pending = User(
        tenant_id=tenant.id,
        email="pending@a.example",
        username="pending-a",
        full_name="Pending",
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        is_active=True,
        email_verified=False,
        has_changed_password=False,
    )
    db_session.add(pending)
    await db_session.commit()
    pending_id = pending.id

    client = _make_app(db_session)
    sender = AsyncMock()
    with client, patch(
        "app.services.email_verification.send_verification_email", sender
    ):
        response = client.post(
            f"/users/{pending_id}/resend-verification",
            headers=_auth_headers(tenant_and_admin["admin"]),
        )

    assert response.status_code == 200, response.text
    sender.assert_awaited()
