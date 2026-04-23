from __future__ import annotations

import secrets
import socket
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_db, get_service_token_tenant, require_role
from app.core.licensing.keys import compute_server_hash, sign_license
from app.core.licensing.state import get_license_state, is_saas_mode
from app.core.licensing.validator import LicenseStatus
from app.models.issued_license import IssuedLicense
from app.models.user import User

router = APIRouter(prefix="/api/licensing", tags=["licensing"])


class IssueLicenseRequest(BaseModel):
    tenant_name: str = Field(min_length=1, max_length=200)
    server_hostname: str = Field(min_length=1, max_length=255)
    db_name: str = Field(min_length=1, max_length=255)
    tier: str = Field(default="enterprise", pattern=r"^(starter|professional|enterprise)$")
    max_users: int = Field(default=0, ge=0)
    features: list[str] = Field(default_factory=list)
    notes: str | None = None
    expires_at: datetime | None = None


class IssueLicenseResponse(BaseModel):
    jti: str
    license_key: str
    issued_at: datetime


class IssuedLicenseResponse(BaseModel):
    jti: str
    tenant_name: str
    server_hash: str
    tier: str
    max_users: int
    features: list[str]
    issued_at: datetime
    issued_by: int | None = None
    expires_at: datetime | None = None
    revoked: bool
    revoked_at: datetime | None = None
    revoke_mode: str | None = None
    last_verified: datetime | None = None
    last_active_users: int | None = None
    last_version: str | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}


class RevokeLicenseResponse(BaseModel):
    revoked: bool
    jti: str
    revoke_mode: str


class ValidateLicenseRequest(BaseModel):
    jti: str = Field(min_length=1, max_length=64)
    server_hostname: str = Field(min_length=1, max_length=255)
    db_name: str = Field(min_length=1, max_length=255)
    version: str = Field(default="unknown", max_length=30)
    active_users: int = Field(default=0, ge=0)


class ValidateLicenseResponse(BaseModel):
    valid: bool
    reason: str | None = None
    revoke_mode: str | None = None
    tier: str | None = None
    max_users: int | None = None
    features: list[str] | None = None
    next_verify_by: datetime | None = None


class LicenseStatusResponse(BaseModel):
    status: LicenseStatus
    tier: str
    max_users: int
    features: list[str]
    grace_until: datetime | None = None
    message: str
    next_verify_by: datetime | None = None


@router.post("/issue", response_model=IssueLicenseResponse)
async def issue_license(
    body: IssueLicenseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("PLATFORM_ADMIN")),
) -> IssueLicenseResponse:
    if not settings.LICENSE_SIGNING_KEY_PEM or not settings.LICENSE_SERVER_HASH_SALT:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="License signing infrastructure is not configured.",
        )

    jti = uuid.uuid4().hex
    issued_at = datetime.now(timezone.utc)
    server_hash = compute_server_hash(
        body.server_hostname,
        body.db_name,
        settings.LICENSE_SERVER_HASH_SALT,
    )
    license_key = sign_license(
        jti=jti,
        tenant_name=body.tenant_name,
        server_hash=server_hash,
        tier=body.tier,
        max_users=body.max_users,
        features=body.features,
        issued_by=current_user.id,
        private_key_pem=settings.LICENSE_SIGNING_KEY_PEM.encode(),
        expires_at=body.expires_at,
    )

    record = IssuedLicense(
        jti=jti,
        tenant_name=body.tenant_name,
        server_hash=server_hash,
        tier=body.tier,
        max_users=body.max_users,
        features=body.features,
        issued_at=issued_at,
        issued_by=current_user.id,
        expires_at=body.expires_at,
        notes=body.notes,
    )
    db.add(record)
    await db.commit()

    return IssueLicenseResponse(jti=jti, license_key=license_key, issued_at=issued_at)


@router.get("/list", response_model=list[IssuedLicenseResponse])
async def list_licenses(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("PLATFORM_ADMIN")),
) -> list[IssuedLicense]:
    result = await db.execute(
        select(IssuedLicense).order_by(IssuedLicense.issued_at.desc())
    )
    return list(result.scalars().all())


@router.post("/revoke/{jti}", response_model=RevokeLicenseResponse)
async def revoke_license(
    jti: str,
    immediate: bool = False,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("PLATFORM_ADMIN")),
) -> RevokeLicenseResponse:
    record = await db.get(IssuedLicense, jti)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="License not found")

    record.revoked = True
    record.revoked_at = datetime.now(timezone.utc)
    record.revoke_mode = "immediate" if immediate else "graceful"
    db.add(record)
    await db.commit()

    return RevokeLicenseResponse(
        revoked=True,
        jti=record.jti,
        revoke_mode=record.revoke_mode,
    )


@router.get("/status/{jti}", response_model=IssuedLicenseResponse)
async def get_license_row(
    jti: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("PLATFORM_ADMIN")),
) -> IssuedLicense:
    record = await db.get(IssuedLicense, jti)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="License not found")
    return record


@router.post("/validate", response_model=ValidateLicenseResponse)
async def validate_license(
    body: ValidateLicenseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ValidateLicenseResponse:
    await _authorize_validate_request(request, db)

    record = await db.get(IssuedLicense, body.jti)
    if record is None:
        return ValidateLicenseResponse(valid=False, reason="unknown license")
    if record.revoked:
        return ValidateLicenseResponse(
            valid=False,
            reason="revoked",
            revoke_mode=record.revoke_mode,
        )
    if record.expires_at and datetime.now(timezone.utc) > record.expires_at:
        return ValidateLicenseResponse(valid=False, reason="expired")

    expected_server_hash = compute_server_hash(
        body.server_hostname,
        body.db_name,
        settings.LICENSE_SERVER_HASH_SALT,
    )
    if not secrets.compare_digest(record.server_hash, expected_server_hash):
        return ValidateLicenseResponse(valid=False, reason="server mismatch")

    now = datetime.now(timezone.utc)
    record.last_verified = now
    record.last_active_users = body.active_users
    record.last_version = body.version
    db.add(record)
    await db.commit()

    return ValidateLicenseResponse(
        valid=True,
        tier=record.tier,
        max_users=record.max_users,
        features=record.features,
        next_verify_by=now + timedelta(hours=settings.LICENSE_PHONE_HOME_INTERVAL_HOURS),
    )


@router.get("/status", response_model=LicenseStatusResponse)
async def get_current_license_status(
    current_user: User = Depends(get_current_user),
) -> LicenseStatusResponse:
    del current_user  # auth-only endpoint; identity is not used further

    if is_saas_mode():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    state = get_license_state()
    return LicenseStatusResponse(
        status=state.status,
        tier=state.tier,
        max_users=state.max_users,
        features=state.features,
        grace_until=state.grace_until,
        message=state.message,
        next_verify_by=state.next_verify_by,
    )


async def _authorize_validate_request(request: Request, db: AsyncSession) -> None:
    shared_secret = request.headers.get("X-License-Validate-Token")
    if settings.LICENSE_VALIDATE_TOKEN and shared_secret:
        if secrets.compare_digest(shared_secret, settings.LICENSE_VALIDATE_TOKEN):
            return

    try:
        await get_service_token_tenant(request=request, db=db)
        return
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized license validation request",
        )
