"""
License validation for self-hosted deployments.

Validation steps:
  1. LOCAL CHECK  - verify JWT signature + server hash.
  2. ONLINE CHECK - confirm not revoked and record telemetry.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from app.core.config import settings

logger = logging.getLogger(__name__)


class LicenseStatus(str, Enum):
    VALID = "valid"
    GRACE = "grace"
    EXPIRED = "expired"
    INVALID = "invalid"
    MISSING = "missing"


@dataclass
class LicenseState:
    status: LicenseStatus
    jti: Optional[str] = None
    tier: str = "unknown"
    max_users: int = 0
    features: list[str] = field(default_factory=list)
    grace_until: Optional[datetime] = None
    message: str = ""
    raw_payload: Optional[dict] = None
    next_verify_by: Optional[datetime] = None

    @property
    def is_operational(self) -> bool:
        return self.status in (LicenseStatus.VALID, LicenseStatus.GRACE)

    @property
    def is_read_only(self) -> bool:
        return self.status == LicenseStatus.EXPIRED

    def has_feature(self, feature: str) -> bool:
        return feature in self.features


def get_license_key() -> Optional[str]:
    if settings.LICENSE_KEY:
        return settings.LICENSE_KEY

    result: dict[str, Optional[str]] = {"value": None}

    def _runner() -> None:
        async def _read() -> Optional[str]:
            from app.db import AsyncSessionLocal
            from app.models.tenant_settings import TenantSettings

            async with AsyncSessionLocal() as db:
                tenant_id = await db.scalar(select(TenantSettings.tenant_id).limit(1))
                if tenant_id is None:
                    return None
                row = await db.scalar(
                    select(TenantSettings.value)
                    .where(TenantSettings.tenant_id == tenant_id)
                    .where(TenantSettings.key == "license_key")
                    .limit(1)
                )
                if not isinstance(row, str) or not row:
                    return None
                try:
                    parsed = json.loads(row)
                    return parsed if isinstance(parsed, str) and parsed else None
                except (TypeError, ValueError):
                    return row

        try:
            result["value"] = asyncio.run(_read())
        except Exception as exc:  # pragma: no cover - best-effort fallback
            logger.warning("license key DB fallback failed: %s", exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join(timeout=10)
    return result["value"]


def local_validate(license_key: str) -> LicenseState:
    from app.core.licensing.keys import verify_license_signature, verify_server_hash

    public_key_pem = settings.LICENSE_PUBLIC_KEY_PEM.encode()
    if not public_key_pem:
        return LicenseState(
            status=LicenseStatus.INVALID,
            message="LICENSE_PUBLIC_KEY_PEM not configured",
        )

    try:
        payload = verify_license_signature(license_key, public_key_pem)
    except Exception as exc:
        return LicenseState(
            status=LicenseStatus.INVALID,
            message=f"Signature verification failed: {exc}",
        )

    server_hostname = socket.gethostname()
    db_name = _extract_db_name(settings.database_url)
    salt = settings.LICENSE_SERVER_HASH_SALT
    if not salt:
        return LicenseState(
            status=LicenseStatus.INVALID,
            message="LICENSE_SERVER_HASH_SALT not configured",
        )

    if not verify_server_hash(payload, server_hostname, db_name, salt):
        return LicenseState(
            status=LicenseStatus.INVALID,
            message="License was not issued for this server/database",
        )

    return LicenseState(
        status=LicenseStatus.VALID,
        jti=payload.get("jti"),
        tier=payload.get("tier", "unknown"),
        max_users=int(payload.get("max_users", 0) or 0),
        features=list(payload.get("features", []) or []),
        raw_payload=payload,
    )


async def online_validate(
    license_key: str,
    local_state: LicenseState,
    active_user_count: int = 0,
    version: str = "unknown",
) -> LicenseState:
    url = f"{settings.LICENSE_API_URL.rstrip('/')}/api/licensing/validate"
    payload = {
        "jti": local_state.jti,
        "server_hostname": socket.gethostname(),
        "db_name": _extract_db_name(settings.database_url),
        "version": version,
        "active_users": active_user_count,
    }
    headers = await _build_online_validate_headers()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if data.get("valid"):
                next_verify_by = _coerce_datetime(data.get("next_verify_by"))
                return LicenseState(
                    status=LicenseStatus.VALID,
                    jti=local_state.jti,
                    tier=data.get("tier", local_state.tier),
                    max_users=int(data.get("max_users", local_state.max_users) or 0),
                    features=list(data.get("features", local_state.features) or []),
                    raw_payload=local_state.raw_payload,
                    next_verify_by=next_verify_by,
                )
            if data.get("revoke_mode") == "graceful":
                return _grace(
                    local_state,
                    message=data.get("reason", "License revoked gracefully"),
                )
            return LicenseState(
                status=LicenseStatus.INVALID,
                jti=local_state.jti,
                message=data.get("reason", "License invalidated by server"),
            )

        logger.warning(
            "license online_validate: unexpected status %s, entering grace",
            response.status_code,
        )
        return _grace(local_state)
    except Exception as exc:
        logger.warning(
            "license online_validate: network error %s, entering grace",
            exc,
        )
        return _grace(local_state)


def _grace(local_state: LicenseState, message: str = "") -> LicenseState:
    grace_until = datetime.now(timezone.utc) + timedelta(
        days=settings.LICENSE_GRACE_PERIOD_DAYS
    )
    return LicenseState(
        status=LicenseStatus.GRACE,
        jti=local_state.jti,
        tier=local_state.tier,
        max_users=local_state.max_users,
        features=local_state.features,
        grace_until=grace_until,
        message=message,
        raw_payload=local_state.raw_payload,
        next_verify_by=grace_until,
    )


def _extract_db_name(database_url: str) -> str:
    try:
        normalized = (
            database_url.replace("+asyncpg", "")
            .replace("+aiosqlite", "")
        )
        parsed = urlparse(normalized)
        if parsed.scheme.startswith("sqlite"):
            return PurePosixPath(parsed.path or "").name or "unknown"
        return (parsed.path or "/unknown").lstrip("/").split("?")[0] or "unknown"
    except Exception:
        return "unknown"


async def _build_online_validate_headers() -> dict[str, str]:
    if settings.LICENSE_VALIDATE_TOKEN:
        return {"X-License-Validate-Token": settings.LICENSE_VALIDATE_TOKEN}

    if not settings.ingestion_service_token:
        return {}

    try:
        from app.db import AsyncSessionLocal
        from app.models.tenant import Tenant

        async with AsyncSessionLocal() as db:
            tenant_id = await db.scalar(select(Tenant.id).limit(1))
        if tenant_id is None:
            return {}
        return {
            "X-Service-Token": settings.ingestion_service_token,
            "X-Tenant-ID": str(tenant_id),
        }
    except Exception as exc:  # pragma: no cover - best-effort auth fallback
        logger.warning("license validate header fallback failed: %s", exc)
        return {}


def _coerce_datetime(value: object) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
