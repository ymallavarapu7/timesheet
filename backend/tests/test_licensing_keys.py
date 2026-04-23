from datetime import datetime, timezone

import jwt

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.licensing.keys import (
    compute_server_hash,
    sign_license,
    verify_license_signature,
    verify_server_hash,
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


def test_compute_server_hash_is_deterministic():
    one = compute_server_hash("host-a", "db-a", "salt-1")
    two = compute_server_hash("host-a", "db-a", "salt-1")

    assert one == two
    assert len(one) == 64


def test_compute_server_hash_differs_for_different_inputs():
    original = compute_server_hash("host-a", "db-a", "salt-1")
    different_host = compute_server_hash("host-b", "db-a", "salt-1")
    different_db = compute_server_hash("host-a", "db-b", "salt-1")

    assert original != different_host
    assert original != different_db


def test_sign_and_verify_license_round_trip():
    private_pem, public_pem = _generate_keypair()
    token = sign_license(
        jti="license-123",
        tenant_name="Acme",
        server_hash=compute_server_hash("acme-host", "acme-db", "salt-1"),
        tier="enterprise",
        max_users=50,
        features=["ingestion", "custom_roles"],
        issued_by=7,
        private_key_pem=private_pem,
        expires_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )

    payload = verify_license_signature(token, public_pem)

    assert payload["jti"] == "license-123"
    assert payload["tier"] == "enterprise"
    assert payload["features"] == ["ingestion", "custom_roles"]


def test_verify_server_hash_correct():
    payload = {"server_hash": compute_server_hash("acme-host", "acme-db", "salt-1")}

    assert verify_server_hash(payload, "acme-host", "acme-db", "salt-1") is True


def test_verify_server_hash_wrong_hostname():
    payload = {"server_hash": compute_server_hash("acme-host", "acme-db", "salt-1")}

    assert verify_server_hash(payload, "wrong-host", "acme-db", "salt-1") is False


def test_verify_license_signature_rejects_tampered_payload():
    private_pem, public_pem = _generate_keypair()
    token = sign_license(
        jti="tamper-test",
        tenant_name="Acme",
        server_hash=compute_server_hash("acme-host", "acme-db", "salt-1"),
        tier="starter",
        max_users=5,
        features=[],
        issued_by=1,
        private_key_pem=private_pem,
    )
    tampered = f"{token}corrupted"

    try:
        verify_license_signature(tampered, public_pem)
    except Exception as exc:
        assert isinstance(exc, jwt.InvalidTokenError)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected InvalidTokenError for tampered token")
