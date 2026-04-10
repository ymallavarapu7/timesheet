"""
Outbound email service for system notifications.
Checks DB-stored platform SMTP config first, falls back to env vars.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


async def _resolve_smtp_config(db: Optional[AsyncSession]) -> dict:
    """Return the effective SMTP config (DB overrides env)."""
    if db is not None:
        try:
            from app.api.platform_settings import get_effective_smtp_config
            return await get_effective_smtp_config(db)
        except Exception as exc:
            logger.warning("Could not load SMTP config from DB: %s", exc)

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


async def send_email(
    to_address: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    db: Optional[AsyncSession] = None,
    smtp_config: Optional[dict] = None,
    tenant_id: Optional[int] = None,
) -> bool:
    """
    Send a single email. Returns True on success, False if SMTP not configured or send fails.

    Sending priority:
      1. Tenant OAuth / mailbox SMTP (if tenant_id provided and method available)
      2. Pre-resolved smtp_config dict (pass from background tasks)
      3. DB-stored platform SMTP config
      4. Env var SMTP config
    """
    # 1. Try tenant-level sending if a tenant_id is available and a DB session exists
    if tenant_id is not None and db is not None:
        try:
            from app.services.tenant_email_service import send_email_for_tenant
            sent = await send_email_for_tenant(db, tenant_id, to_address, subject, body_text, body_html)
            if sent:
                return True
        except Exception as exc:
            logger.warning("Tenant email send failed for tenant %s: %s", tenant_id, exc)

    cfg = smtp_config if smtp_config is not None else await _resolve_smtp_config(db)

    if not cfg["host"]:
        logger.warning("SMTP not configured — email not sent to %s", to_address)
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{cfg['from_name']} <{cfg['from_address']}>"
        msg["To"] = to_address

        msg.attach(MIMEText(body_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
            if cfg["use_tls"]:
                server.starttls()
            if cfg["username"]:
                server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["from_address"], to_address, msg.as_string())
        return True
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_address, exc)
        return False
