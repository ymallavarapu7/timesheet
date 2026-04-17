"""
Email verification service.

Generates secure tokens, stores them on the User record, and sends
(or logs, when SMTP is not configured) the verification email.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.services.email_service import send_email

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_HOURS = 48


def generate_verification_token() -> str:
    """Return a 64-char URL-safe random token."""
    return secrets.token_urlsafe(48)


def set_verification_token(user: User) -> str:
    """Attach a fresh token + expiry to the user object (caller must commit)."""
    token = generate_verification_token()
    user.email_verification_token = token
    user.email_verification_token_expires_at = datetime.now(timezone.utc) + timedelta(
        hours=TOKEN_EXPIRY_HOURS
    )
    user.email_verified = False
    user.email_verified_at = None
    return token


def build_verification_url(token: str) -> str:
    frontend_base = getattr(settings, "frontend_base_url", "http://localhost:5174")
    return f"{frontend_base}/verify-account?token={token}"


async def send_verification_email(
    user: User,
    token: str,
    temporary_password: str,
    smtp_config: dict | None = None,
    tenant_name: str | None = None,
    tenant_id: int | None = None,
    via_tenant_oauth: bool = False,
) -> None:
    """
    Send (or log) the account verification email containing the temp password.
    smtp_config: pre-resolved SMTP dict (pass this when calling from a background
    task so the DB session doesn't need to stay open).
    tenant_name: display name of the tenant, shown in the email body.
    via_tenant_oauth: True when sent from the tenant's own OAuth mailbox.
    """
    verify_url = build_verification_url(token)
    org = tenant_name or "your organisation"

    # Tenant OAuth → branded subject; platform SMTP → generic invite subject
    if via_tenant_oauth:
        subject = f"{org} · You've been invited to TimesheetIQ"
    else:
        subject = f"{org} has invited you to TimesheetIQ"

    body_text = f"""Hello {user.full_name},

{org} has created a TimesheetIQ account for you.

Your temporary password is: {temporary_password}

To activate your account and set a permanent password, click the link below
(valid for {TOKEN_EXPIRY_HOURS} hours):

{verify_url}

After clicking the link, you will be asked to enter the temporary password above
and choose a new password before you can access the application.

If you were not expecting this email, please ignore it.

— The TimesheetIQ Team
"""

    body_html = f"""
<div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;color:#1e293b;">
  <p>Hello {user.full_name},</p>
  <p><strong>{org}</strong> has created a TimesheetIQ account for you.</p>
  <p>Your temporary password is:</p>
  <p style="font-family:monospace;font-size:16px;background:#f1f5f9;padding:10px 16px;border-radius:6px;display:inline-block;">{temporary_password}</p>
  <p>Click the button below to verify your account and set a permanent password:</p>
  <p>
    <a href="{verify_url}" style="display:inline-block;padding:12px 24px;background:#2563EB;color:#fff;border-radius:6px;text-decoration:none;font-weight:600;">
      Verify my account
    </a>
  </p>
  <p style="color:#64748b;font-size:13px;">This link expires in {TOKEN_EXPIRY_HOURS} hours.</p>
  <p style="color:#64748b;font-size:13px;">If you were not expecting this email, please ignore it.</p>
  <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
  <p style="color:#94a3b8;font-size:12px;">TimesheetIQ · Sent by {org}</p>
</div>
"""

    # Try tenant OAuth first (opens its own DB session)
    sent = False
    if tenant_id is not None:
        try:
            from app.db import AsyncSessionLocal
            from app.services.tenant_email_service import send_email_for_tenant
            async with AsyncSessionLocal() as db:
                sent = await send_email_for_tenant(db, tenant_id, user.email, subject, body_text, body_html)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Tenant OAuth send failed: %s", exc)

    # Fall back to platform SMTP
    if not sent:
        sent = await send_email(
            to_address=user.email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            smtp_config=smtp_config,
        )

    if not sent:
        # SMTP not configured — print to stdout so it's always visible in container logs.
        print(
            f"\n{'='*60}\n"
            f"[EMAIL VERIFICATION — SMTP NOT CONFIGURED]\n"
            f"  User:          {user.email}\n"
            f"  Temp password: {temporary_password}\n"
            f"  Verify URL:    {verify_url}\n"
            f"{'='*60}\n",
            flush=True,
        )


async def mark_email_verified(db: AsyncSession, user: User) -> None:
    """Mark the user as verified (caller must commit).

    We leave email_verification_token in place until it naturally expires so
    page-refresh during the set-password step doesn't kick the user out with
    an "invalid token" error. The token is still useless after verify — the
    verify endpoint returns a no-op for already-verified users — but keeping
    it around makes the flow idempotent.
    """
    user.email_verified = True
    user.email_verified_at = datetime.now(timezone.utc)
    user.has_changed_password = True
    db.add(user)
