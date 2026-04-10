"""
Tenant-level outbound email service.

Sending priority for a given tenant:
  1. Tenant mailbox OAuth (Gmail API / Microsoft Graph Send)
  2. Tenant SMTP credentials stored on the mailbox record (smtp_host etc.) — placeholder
  3. Platform-level SMTP config (DB-stored or env vars) — existing fallback.
"""
import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mailbox import Mailbox, MailboxAuthType, OAuthProvider

logger = logging.getLogger(__name__)


async def _get_active_oauth_mailbox(db: AsyncSession, tenant_id: int) -> Optional[Mailbox]:
    """Return the first active OAuth mailbox for the tenant, or None."""
    result = await db.execute(
        select(Mailbox)
        .where(Mailbox.tenant_id == tenant_id)
        .where(Mailbox.is_active == True)  # noqa: E712
        .where(Mailbox.auth_type == MailboxAuthType.oauth2)
        .where(Mailbox.oauth_provider.isnot(None))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _build_raw_message(
    from_address: str,
    to_address: str,
    subject: str,
    body_text: str,
    body_html: Optional[str],
) -> str:
    """Build a RFC2822 message and return it base64url-encoded (for Gmail API)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address
    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return raw


async def _send_via_gmail_api(
    mailbox: Mailbox,
    db: AsyncSession,
    to_address: str,
    subject: str,
    body_text: str,
    body_html: Optional[str],
) -> bool:
    """Send email using the Gmail REST API (gmail.send scope)."""
    import httpx
    from app.services.imap import _get_fresh_access_token

    access_token = await _get_fresh_access_token(mailbox, db)
    from_address = mailbox.oauth_email or ""
    raw = _build_raw_message(from_address, to_address, subject, body_text, body_html)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
        )

    if response.status_code in (200, 201):
        logger.info("Sent email via Gmail API for tenant %s to %s", mailbox.tenant_id, to_address)
        return True

    logger.warning(
        "Gmail API send failed (status %s): %s",
        response.status_code, response.text[:200],
    )
    return False


async def _send_via_graph_api(
    mailbox: Mailbox,
    db: AsyncSession,
    to_address: str,
    subject: str,
    body_text: str,
    body_html: Optional[str],
) -> bool:
    """Send email using the Microsoft Graph API (Mail.Send scope)."""
    import httpx
    from app.services.imap import _get_fresh_access_token

    access_token = await _get_fresh_access_token(mailbox, db)

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML" if body_html else "Text",
                "content": body_html or body_text,
            },
            "toRecipients": [{"emailAddress": {"address": to_address}}],
        },
        "saveToSentItems": "false",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code == 202:
        logger.info("Sent email via Graph API for tenant %s to %s", mailbox.tenant_id, to_address)
        return True

    logger.warning(
        "Graph API send failed (status %s): %s",
        response.status_code, response.text[:200],
    )
    return False


async def send_email_for_tenant(
    db: AsyncSession,
    tenant_id: int,
    to_address: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
) -> bool:
    """
    Send an email on behalf of a tenant using their OAuth mailbox.
    Returns True if sent, False if unavailable or failed (caller falls back to platform SMTP).
    """
    mailbox = await _get_active_oauth_mailbox(db, tenant_id)
    if mailbox is None:
        return False

    try:
        if mailbox.oauth_provider == OAuthProvider.google:
            return await _send_via_gmail_api(mailbox, db, to_address, subject, body_text, body_html)
        elif mailbox.oauth_provider == OAuthProvider.microsoft:
            return await _send_via_graph_api(mailbox, db, to_address, subject, body_text, body_html)
    except Exception as exc:
        logger.warning(
            "Tenant %s: OAuth send failed (%s) — falling through to platform SMTP",
            tenant_id, exc,
        )

    return False
