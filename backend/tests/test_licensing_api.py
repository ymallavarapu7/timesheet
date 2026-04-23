from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import models  # noqa: F401
from app.api import auth, licensing
from app.core.config import settings
from app.core.security import get_password_hash, hash_service_token
from app.db import get_db
from app.models.base import Base
from app.models.issued_license import IssuedLicense
from app.models.service_token import ServiceToken
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - shim
    return "JSON"


REPO_ROOT = Path(__file__).resolve().parents[2]


def _generate_keypair() -> tuple[bytes, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    with TemporaryDirectory(dir=REPO_ROOT) as temp_dir:
        db_path = Path(temp_dir) / "licensing_api.db"
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
async def api_client(db_session: AsyncSession):
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(licensing.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


async def _create_user(
    db_session: AsyncSession,
    *,
    role: UserRole,
    email: str,
    username: str,
    tenant: Tenant | None = None,
) -> User:
    user = User(
        tenant=tenant,
        email=email,
        username=username,
        full_name=username.title(),
        hashed_password=get_password_hash("password"),
        role=role,
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": "password"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_issue_license_requires_platform_admin(
    db_session: AsyncSession,
    api_client: TestClient,
):
    tenant = Tenant(name="Tenant A", slug="tenant-a", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.commit()
    await _create_user(
        db_session,
        role=UserRole.ADMIN,
        email="admin-license@example.com",
        username="admin-license",
        tenant=tenant,
    )
    headers = await _login(api_client, "admin-license@example.com")

    response = api_client.post(
        "/api/licensing/issue",
        headers=headers,
        json={
            "tenant_name": "Tenant A",
            "server_hostname": "customer-host",
            "db_name": "customerdb",
            "tier": "enterprise",
            "max_users": 25,
            "features": ["ingestion"],
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_issue_license_returns_503_when_signing_key_missing(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    api_client: TestClient,
):
    monkeypatch.setattr(settings, "LICENSE_SIGNING_KEY_PEM", "")
    monkeypatch.setattr(settings, "LICENSE_SERVER_HASH_SALT", "")
    await _create_user(
        db_session,
        role=UserRole.PLATFORM_ADMIN,
        email="platform-license@example.com",
        username="platform-license",
    )
    headers = await _login(api_client, "platform-license@example.com")

    response = api_client.post(
        "/api/licensing/issue",
        headers=headers,
        json={
            "tenant_name": "Tenant A",
            "server_hostname": "customer-host",
            "db_name": "customerdb",
            "tier": "enterprise",
            "max_users": 25,
            "features": ["ingestion"],
        },
    )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_issue_license_creates_row_and_returns_jwt(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    api_client: TestClient,
):
    private_pem, _ = _generate_keypair()
    monkeypatch.setattr(settings, "LICENSE_SIGNING_KEY_PEM", private_pem.decode())
    monkeypatch.setattr(settings, "LICENSE_SERVER_HASH_SALT", "salt-1")
    await _create_user(
        db_session,
        role=UserRole.PLATFORM_ADMIN,
        email="platform-create@example.com",
        username="platform-create",
    )
    headers = await _login(api_client, "platform-create@example.com")

    response = api_client.post(
        "/api/licensing/issue",
        headers=headers,
        json={
            "tenant_name": "Tenant A",
            "server_hostname": "customer-host",
            "db_name": "customerdb",
            "tier": "enterprise",
            "max_users": 25,
            "features": ["ingestion"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["license_key"]

    record = await db_session.get(IssuedLicense, body["jti"])
    assert record is not None
    assert record.jti == body["jti"]


@pytest.mark.asyncio
async def test_validate_endpoint_returns_valid_for_known_jti(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    api_client: TestClient,
):
    from app.core.licensing.keys import compute_server_hash

    tenant = Tenant(name="Tenant A", slug="tenant-a-validate", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.commit()
    token = "service-token-1"
    db_session.add(
        ServiceToken(
            name="License Validate",
            token_hash=hash_service_token(token),
            tenant_id=tenant.id,
            issuer="licensing",
            is_active=True,
        )
    )
    db_session.add(
        IssuedLicense(
            jti="known-jti",
            tenant_name="Tenant A",
            server_hash=compute_server_hash("customer-host", "customerdb", "salt-1"),
            tier="enterprise",
            max_users=20,
            features=["ingestion"],
            issued_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    monkeypatch.setattr(settings, "LICENSE_SERVER_HASH_SALT", "salt-1")

    response = api_client.post(
        "/api/licensing/validate",
        headers={"X-Service-Token": token, "X-Tenant-ID": str(tenant.id)},
        json={
            "jti": "known-jti",
            "server_hostname": "customer-host",
            "db_name": "customerdb",
            "version": "1.2.3",
            "active_users": 7,
        },
    )

    assert response.status_code == 200
    assert response.json()["valid"] is True


@pytest.mark.asyncio
async def test_validate_endpoint_returns_invalid_for_revoked(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    api_client: TestClient,
):
    tenant = Tenant(name="Tenant B", slug="tenant-b-validate", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.commit()
    token = "service-token-2"
    db_session.add(
        ServiceToken(
            name="License Validate",
            token_hash=hash_service_token(token),
            tenant_id=tenant.id,
            issuer="licensing",
            is_active=True,
        )
    )
    db_session.add(
        IssuedLicense(
            jti="revoked-jti",
            tenant_name="Tenant B",
            server_hash="ignored",
            tier="enterprise",
            max_users=20,
            features=[],
            issued_at=datetime.now(timezone.utc),
            revoked=True,
        )
    )
    await db_session.commit()
    monkeypatch.setattr(settings, "LICENSE_SERVER_HASH_SALT", "salt-1")

    response = api_client.post(
        "/api/licensing/validate",
        headers={"X-Service-Token": token, "X-Tenant-ID": str(tenant.id)},
        json={
            "jti": "revoked-jti",
            "server_hostname": "customer-host",
            "db_name": "customerdb",
            "version": "1.2.3",
            "active_users": 7,
        },
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["reason"] == "revoked"


@pytest.mark.asyncio
async def test_validate_endpoint_returns_invalid_for_server_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    api_client: TestClient,
):
    from app.core.licensing.keys import compute_server_hash

    tenant = Tenant(name="Tenant C", slug="tenant-c-validate", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.commit()
    token = "service-token-3"
    db_session.add(
        ServiceToken(
            name="License Validate",
            token_hash=hash_service_token(token),
            tenant_id=tenant.id,
            issuer="licensing",
            is_active=True,
        )
    )
    db_session.add(
        IssuedLicense(
            jti="mismatch-jti",
            tenant_name="Tenant C",
            server_hash=compute_server_hash("different-host", "customerdb", "salt-1"),
            tier="enterprise",
            max_users=20,
            features=[],
            issued_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    monkeypatch.setattr(settings, "LICENSE_SERVER_HASH_SALT", "salt-1")

    response = api_client.post(
        "/api/licensing/validate",
        headers={"X-Service-Token": token, "X-Tenant-ID": str(tenant.id)},
        json={
            "jti": "mismatch-jti",
            "server_hostname": "customer-host",
            "db_name": "customerdb",
            "version": "1.2.3",
            "active_users": 7,
        },
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["reason"] == "server mismatch"


@pytest.mark.asyncio
async def test_revoke_sets_revoked_flag(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    api_client: TestClient,
):
    private_pem, _ = _generate_keypair()
    monkeypatch.setattr(settings, "LICENSE_SIGNING_KEY_PEM", private_pem.decode())
    monkeypatch.setattr(settings, "LICENSE_SERVER_HASH_SALT", "salt-1")
    await _create_user(
        db_session,
        role=UserRole.PLATFORM_ADMIN,
        email="platform-revoke@example.com",
        username="platform-revoke",
    )
    db_session.add(
        IssuedLicense(
            jti="revoke-me",
            tenant_name="Tenant D",
            server_hash="hash",
            tier="starter",
            max_users=5,
            features=[],
            issued_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    headers = await _login(api_client, "platform-revoke@example.com")

    response = api_client.post(
        "/api/licensing/revoke/revoke-me?immediate=true",
        headers=headers,
    )

    assert response.status_code == 200
    record = await db_session.get(IssuedLicense, "revoke-me")
    assert record.revoked is True
    assert record.revoke_mode == "immediate"


@pytest.mark.asyncio
async def test_status_endpoint_returns_404_in_saas_mode(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    api_client: TestClient,
):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "saas")
    tenant = Tenant(name="Tenant D", slug="tenant-d-status", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.commit()
    await _create_user(
        db_session,
        role=UserRole.ADMIN,
        email="admin-status@example.com",
        username="admin-status",
        tenant=tenant,
    )
    headers = await _login(api_client, "admin-status@example.com")

    response = api_client.get("/api/licensing/status", headers=headers)

    assert response.status_code == 404
