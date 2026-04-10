"""
Platform-level settings API.
Only PLATFORM_ADMIN users can read or update these settings.
The SMTP password is stored encrypted; all other values stored plaintext.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_role
from app.models.platform_settings import PlatformSettings
from app.models.user import User
from app.services.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform/settings", tags=["platform-settings"])

# Settings keys stored in the DB
SMTP_KEYS = [
    "smtp_host",
    "smtp_port",
    "smtp_username",
    "smtp_password",       # stored encrypted
    "smtp_from_address",
    "smtp_from_name",
    "smtp_use_tls",
]

SENSITIVE_KEYS = {"smtp_password"}


# ── Schemas ────────────────────────────────────────────────────────────────


class SmtpConfig(BaseModel):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""           # empty = not set / masked on GET
    smtp_from_address: str = ""
    smtp_from_name: str = ""
    smtp_use_tls: bool = True


class SmtpConfigUpdate(BaseModel):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: Optional[str] = None  # None = don't change existing
    smtp_from_address: str = ""
    smtp_from_name: str = ""
    smtp_use_tls: bool = True


class SmtpConfigResponse(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password_set: bool           # whether a password has been stored
    smtp_from_address: str
    smtp_from_name: str
    smtp_use_tls: bool
    source: str                       # "database" | "environment"


# ── Helpers ────────────────────────────────────────────────────────────────


async def _get_setting(db: AsyncSession, key: str) -> Optional[str]:
    result = await db.execute(
        select(PlatformSettings).where(PlatformSettings.key == key)
    )
    row = result.scalar_one_or_none()
    return row.value if row else None


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(
        select(PlatformSettings).where(PlatformSettings.key == key)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = PlatformSettings(key=key, value=value)
        db.add(row)
    else:
        row.value = value


# ── Routes ─────────────────────────────────────────────────────────────────


@router.get("/smtp", response_model=SmtpConfigResponse)
async def get_smtp_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("PLATFORM_ADMIN")),
) -> SmtpConfigResponse:
    """Return current SMTP configuration (DB takes precedence over env vars)."""
    from app.core.config import settings

    db_host = await _get_setting(db, "smtp_host")

    if db_host is not None:
        # DB config present — read all keys from DB
        source = "database"
        host = db_host or ""
        port_raw = await _get_setting(db, "smtp_port")
        port = int(port_raw) if port_raw else 587
        username = await _get_setting(db, "smtp_username") or ""
        enc_pwd = await _get_setting(db, "smtp_password")
        password_set = bool(enc_pwd)
        from_address = await _get_setting(db, "smtp_from_address") or ""
        from_name = await _get_setting(db, "smtp_from_name") or ""
        tls_raw = await _get_setting(db, "smtp_use_tls")
        use_tls = tls_raw.lower() in ("true", "1", "yes") if tls_raw else True
    else:
        # Fall back to env / config
        source = "environment"
        host = settings.smtp_host
        port = settings.smtp_port
        username = settings.smtp_username
        password_set = bool(settings.smtp_password)
        from_address = settings.smtp_from_address
        from_name = settings.smtp_from_name
        use_tls = settings.smtp_use_tls

    return SmtpConfigResponse(
        smtp_host=host,
        smtp_port=port,
        smtp_username=username,
        smtp_password_set=password_set,
        smtp_from_address=from_address,
        smtp_from_name=from_name,
        smtp_use_tls=use_tls,
        source=source,
    )


@router.put("/smtp", response_model=SmtpConfigResponse)
async def update_smtp_config(
    payload: SmtpConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("PLATFORM_ADMIN")),
) -> SmtpConfigResponse:
    """Save SMTP configuration to the database."""
    await _set_setting(db, "smtp_host", payload.smtp_host)
    await _set_setting(db, "smtp_port", str(payload.smtp_port))
    await _set_setting(db, "smtp_username", payload.smtp_username)
    await _set_setting(db, "smtp_from_address", payload.smtp_from_address)
    await _set_setting(db, "smtp_from_name", payload.smtp_from_name)
    await _set_setting(db, "smtp_use_tls", "true" if payload.smtp_use_tls else "false")

    if payload.smtp_password is not None:
        encrypted = encrypt(payload.smtp_password) if payload.smtp_password else ""
        await _set_setting(db, "smtp_password", encrypted)

    await db.commit()

    # Return updated state
    password_set = bool(await _get_setting(db, "smtp_password"))
    return SmtpConfigResponse(
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        smtp_username=payload.smtp_username,
        smtp_password_set=password_set,
        smtp_from_address=payload.smtp_from_address,
        smtp_from_name=payload.smtp_from_name,
        smtp_use_tls=payload.smtp_use_tls,
        source="database",
    )


@router.delete("/smtp")
async def clear_smtp_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("PLATFORM_ADMIN")),
) -> dict:
    """Remove all DB-stored SMTP settings so env vars take effect again."""
    for key in SMTP_KEYS:
        result = await db.execute(
            select(PlatformSettings).where(PlatformSettings.key == key)
        )
        row = result.scalar_one_or_none()
        if row:
            await db.delete(row)
    await db.commit()
    return {"message": "SMTP configuration cleared — environment variables will be used."}


# ── Public helper for email service ───────────────────────────────────────


async def get_effective_smtp_config(db: AsyncSession) -> dict:
    """
    Returns the effective SMTP config dict for use by the email service.
    DB config overrides env vars; returns env config if no DB config set.
    """
    from app.core.config import settings

    db_host = await _get_setting(db, "smtp_host")
    if db_host is not None:
        port_raw = await _get_setting(db, "smtp_port")
        enc_pwd = await _get_setting(db, "smtp_password")
        password = ""
        if enc_pwd:
            try:
                password = decrypt(enc_pwd)
            except Exception:
                logger.warning("Failed to decrypt SMTP password from DB")
        tls_raw = await _get_setting(db, "smtp_use_tls")
        return {
            "host": db_host or "",
            "port": int(port_raw) if port_raw else 587,
            "username": await _get_setting(db, "smtp_username") or "",
            "password": password,
            "from_address": await _get_setting(db, "smtp_from_address") or "",
            "from_name": await _get_setting(db, "smtp_from_name") or "",
            "use_tls": tls_raw.lower() in ("true", "1", "yes") if tls_raw else True,
        }

    # Env fallback
    return {
        "host": settings.smtp_host,
        "port": settings.smtp_port,
        "username": settings.smtp_username,
        "password": settings.smtp_password,
        "from_address": settings.smtp_from_address,
        "from_name": settings.smtp_from_name,
        "use_tls": settings.smtp_use_tls,
    }
