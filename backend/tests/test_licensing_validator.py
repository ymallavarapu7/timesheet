from datetime import datetime, timezone

import httpx
import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.core.licensing.keys import compute_server_hash, sign_license
from app.core.licensing.validator import (
    LicenseState,
    LicenseStatus,
    _extract_db_name,
    local_validate,
    online_validate,
)


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


def test_local_validate_returns_invalid_when_no_public_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "LICENSE_PUBLIC_KEY_PEM", "")
    state = local_validate("any-key")

    assert state.status == LicenseStatus.INVALID


def test_local_validate_returns_invalid_for_bad_token(monkeypatch: pytest.MonkeyPatch):
    _, public_pem = _generate_keypair()
    monkeypatch.setattr(settings, "LICENSE_PUBLIC_KEY_PEM", public_pem.decode())
    monkeypatch.setattr(settings, "LICENSE_SERVER_HASH_SALT", "salt-1")

    state = local_validate("not-a-jwt")

    assert state.status == LicenseStatus.INVALID


def test_local_validate_returns_invalid_for_wrong_server(monkeypatch: pytest.MonkeyPatch):
    private_pem, public_pem = _generate_keypair()
    monkeypatch.setattr(settings, "LICENSE_PUBLIC_KEY_PEM", public_pem.decode())
    monkeypatch.setattr(settings, "LICENSE_SERVER_HASH_SALT", "salt-1")
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://user:pass@host:5432/customerdb")
    monkeypatch.setattr("socket.gethostname", lambda: "actual-host")
    token = sign_license(
        jti="wrong-server",
        tenant_name="Acme",
        server_hash=compute_server_hash("other-host", "customerdb", "salt-1"),
        tier="professional",
        max_users=10,
        features=["ingestion"],
        issued_by=1,
        private_key_pem=private_pem,
    )

    state = local_validate(token)

    assert state.status == LicenseStatus.INVALID
    assert "server" in state.message.lower()


def test_local_validate_returns_valid_for_good_token(monkeypatch: pytest.MonkeyPatch):
    private_pem, public_pem = _generate_keypair()
    monkeypatch.setattr(settings, "LICENSE_PUBLIC_KEY_PEM", public_pem.decode())
    monkeypatch.setattr(settings, "LICENSE_SERVER_HASH_SALT", "salt-1")
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://user:pass@host:5432/customerdb")
    monkeypatch.setattr("socket.gethostname", lambda: "customer-host")
    token = sign_license(
        jti="good-token",
        tenant_name="Acme",
        server_hash=compute_server_hash("customer-host", "customerdb", "salt-1"),
        tier="enterprise",
        max_users=100,
        features=["ingestion", "api_access"],
        issued_by=1,
        private_key_pem=private_pem,
    )

    state = local_validate(token)

    assert state.status == LicenseStatus.VALID
    assert state.tier == "enterprise"
    assert state.features == ["ingestion", "api_access"]


@pytest.mark.asyncio
async def test_online_validate_returns_valid_on_200_response(monkeypatch: pytest.MonkeyPatch):
    class MockResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "valid": True,
                "tier": "enterprise",
                "max_users": 500,
                "features": ["ingestion"],
                "next_verify_by": datetime.now(timezone.utc).isoformat(),
            }

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return MockResponse()

    monkeypatch.setattr("app.core.licensing.validator.httpx.AsyncClient", MockClient)
    local_state = LicenseState(
        status=LicenseStatus.VALID,
        jti="valid-online",
        tier="starter",
        max_users=10,
        features=[],
    )

    state = await online_validate("license-key", local_state)

    assert state.status == LicenseStatus.VALID
    assert state.tier == "enterprise"
    assert state.features == ["ingestion"]


@pytest.mark.asyncio
async def test_online_validate_returns_grace_on_network_error(monkeypatch: pytest.MonkeyPatch):
    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr("app.core.licensing.validator.httpx.AsyncClient", MockClient)
    local_state = LicenseState(
        status=LicenseStatus.VALID,
        jti="grace-online",
        tier="starter",
        max_users=10,
        features=[],
    )

    state = await online_validate("license-key", local_state)

    assert state.status == LicenseStatus.GRACE


@pytest.mark.asyncio
async def test_online_validate_returns_invalid_on_revoked(monkeypatch: pytest.MonkeyPatch):
    class MockResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"valid": False, "reason": "revoked"}

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return MockResponse()

    monkeypatch.setattr("app.core.licensing.validator.httpx.AsyncClient", MockClient)
    local_state = LicenseState(
        status=LicenseStatus.VALID,
        jti="revoked-online",
        tier="starter",
        max_users=10,
        features=[],
    )

    state = await online_validate("license-key", local_state)

    assert state.status == LicenseStatus.INVALID
    assert state.message == "revoked"


def test_extract_db_name_from_postgres_url():
    assert _extract_db_name("postgresql+asyncpg://user:pass@host:5432/mydb") == "mydb"


def test_extract_db_name_from_sqlite_url():
    assert _extract_db_name("sqlite+aiosqlite:///./test.db") == "test.db"
