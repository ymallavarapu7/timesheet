"""
License key cryptography.

Uses RS256 (asymmetric). The private key signs licenses; the public key
is embedded in the application to verify them. Keeping the private key
out of this module is the caller's responsibility.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Optional

import jwt
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)


def compute_server_hash(
    server_hostname: str,
    db_name: str,
    salt: str,
) -> str:
    raw = f"{server_hostname}:{db_name}:{salt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sign_license(
    *,
    jti: str,
    tenant_name: str,
    server_hash: str,
    tier: str,
    max_users: int,
    features: list[str],
    issued_by: int,
    private_key_pem: bytes,
    expires_at: Optional[datetime] = None,
) -> str:
    payload: dict[str, object] = {
        "iss": "licenses.yourdomain.com",
        "jti": jti,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "sub": tenant_name,
        "server_hash": server_hash,
        "tier": tier,
        "max_users": max_users,
        "features": features,
        "issued_by": issued_by,
    }
    if expires_at is not None:
        payload["expires_at"] = expires_at.isoformat()

    private_key = load_pem_private_key(private_key_pem, password=None)
    return jwt.encode(payload, private_key, algorithm="RS256")


def verify_license_signature(
    token: str,
    public_key_pem: bytes,
) -> dict:
    public_key = load_pem_public_key(public_key_pem)
    return jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        options={"verify_exp": False},
    )


def verify_server_hash(
    token_payload: dict,
    server_hostname: str,
    db_name: str,
    salt: str,
) -> bool:
    expected = compute_server_hash(server_hostname, db_name, salt)
    return hmac.compare_digest(token_payload.get("server_hash", ""), expected)
