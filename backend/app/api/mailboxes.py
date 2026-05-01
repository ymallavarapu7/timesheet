import base64
import hashlib
import hmac
import html
import json
import secrets
from datetime import datetime, timedelta, timezone
from time import perf_counter, time
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel as PydanticBaseModel
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_tenant_db, require_ingestion_enabled, require_role
from app.crud.mailbox import (
    create_mailbox,
    delete_mailbox,
    get_mailbox,
    list_mailboxes,
    update_mailbox,
)
from app.models.client import Client
from app.models.mailbox import Mailbox, MailboxAuthType, MailboxProtocol, OAuthProvider
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.ingestion import (
    ConnectionTestResult,
    MailboxCreate,
    MailboxRead,
    MailboxUpdate,
    OAuthConnectResponse,
)
from app.services.activity import (
    TENANT_ADMIN_ACTIVITY_SCOPE,
    build_activity_event,
    record_activity_events,
)
from app.services.encryption import encrypt
from app.services.imap import test_connection

router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])
oauth_router = APIRouter(prefix="/auth/oauth", tags=["mailboxes"])

GOOGLE_IMAP_HOST = "imap.gmail.com"
MICROSOFT_IMAP_HOST = "outlook.office365.com"
OAUTH_STATE_MAX_AGE_SECONDS = 600


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _decode_jwt_payload(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        return json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except Exception:
        return {}


def _state_signature(payload: str) -> str:
    digest = hmac.new(
        settings.secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64url_encode(digest)


def _build_oauth_state(provider: str, tenant_id: int, user_id: int) -> str:
    """Construct a signed OAuth state token bound to the initiating user.

    The HMAC signature with the server's SECRET_KEY prevents tampering with
    any payload field, so user_id is trustworthy on callback even though the
    callback itself runs without an Authorization header (OAuth providers
    redirect plain GET; we cannot require an auth header on that hop).

    On callback, we verify the user still exists and is still active and
    in the same tenant the state was issued for. The mailbox creation is
    then attributed to that user via the activity log, which is what the
    audit needed: a trustworthy "who connected this mailbox" anchor that
    cannot be silently swapped by handing the popup to another admin.
    """
    payload = json.dumps(
        {
            "provider": provider,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "issued_at": int(time()),
            "nonce": secrets.token_urlsafe(12),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{_b64url_encode(payload.encode('utf-8'))}.{_state_signature(payload)}"


def _parse_oauth_state(state: str) -> dict:
    try:
        encoded_payload, signature = state.split(".", 1)
        payload = _b64url_decode(encoded_payload).decode("utf-8")
        expected_signature = _state_signature(payload)
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("OAuth state signature mismatch.")

        data = json.loads(payload)
        if int(time()) - int(data["issued_at"]) > OAUTH_STATE_MAX_AGE_SECONDS:
            raise ValueError("OAuth state has expired.")
        tenant_id = int(data["tenant_id"])
        provider = str(data["provider"])
        # user_id is required on new states. States issued before this fix
        # don't carry it; we treat those as expired (force re-auth) rather
        # than silently downgrading the binding.
        if "user_id" not in data:
            raise ValueError("OAuth state is missing a user binding (re-initiate).")
        user_id = int(data["user_id"])
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("OAuth state is invalid or expired.") from exc

    return {
        "tenant_id": tenant_id,
        "provider": provider,
        "user_id": user_id,
    }


def _oauth_mailbox_defaults(provider: OAuthProvider) -> dict:
    if provider == OAuthProvider.google:
        return {
            "host": GOOGLE_IMAP_HOST,
            "port": 993,
            "protocol": MailboxProtocol.imap,
            "label_prefix": "Google Workspace",
        }

    return {
        "host": None,
        "port": None,
        "protocol": MailboxProtocol.graph,
        "label_prefix": "Microsoft 365",
    }


def _resolve_oauth_postmessage_origin() -> str:
    for candidate in settings.cors_origins:
        if not candidate:
            continue
        try:
            parsed = urlparse(candidate)
        except ValueError:
            continue
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    raise RuntimeError(
        "OAuth popup cannot post back: CORS_ORIGINS is empty or contains no valid http(s) origin. "
        "Configure CORS_ORIGINS with the frontend URL(s) before initiating OAuth flows."
    )


def _oauth_popup_response(status_value: str, message: str, mailbox_id: int | None = None) -> HTMLResponse:
    frontend_origin = _resolve_oauth_postmessage_origin()
    payload = {
        "type": "mailbox-oauth",
        "status": status_value,
        "message": message,
        "mailbox_id": mailbox_id,
    }
    payload_json = json.dumps(payload)
    safe_message = html.escape(message)
    title = "Mailbox Connected" if status_value == "success" else "Mailbox Connection Failed"
    action_text = "You can close this window." if status_value == "success" else "You can close this window and try again."
    page = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(title)}</title>
    <style>
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #0b1020;
        color: #f5f7fb;
        font-family: system-ui, sans-serif;
      }}
      main {{
        width: min(32rem, calc(100vw - 2rem));
        border: 1px solid rgba(245, 247, 251, 0.12);
        background: rgba(16, 24, 40, 0.92);
        border-radius: 20px;
        padding: 2rem;
        box-shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
      }}
      h1 {{
        margin: 0 0 0.75rem;
        font-size: 1.5rem;
      }}
      p {{
        margin: 0;
        line-height: 1.6;
        color: rgba(245, 247, 251, 0.84);
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>{html.escape(title)}</h1>
      <p>{safe_message}</p>
      <p style="margin-top:0.85rem;">{html.escape(action_text)}</p>
    </main>
    <script>
      (function() {{
        const payload = {payload_json};
        if (window.opener && !window.opener.closed) {{
          window.opener.postMessage(payload, "{frontend_origin}");
          setTimeout(function() {{ window.close(); }}, 250);
        }}
      }})();
    </script>
  </body>
</html>"""
    # Relax CSP just for this response so the inline postMessage script runs.
    # Script body is fully server-controlled.
    return HTMLResponse(
        page,
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; "
                "script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; "
                "frame-ancestors 'none'; "
                "base-uri 'none'"
            )
        },
    )


def _mask_mailbox(mailbox: Mailbox) -> dict:
    return {
        "id": mailbox.id,
        "tenant_id": mailbox.tenant_id,
        "label": mailbox.label,
        "protocol": _enum_value(mailbox.protocol),
        "auth_type": _enum_value(mailbox.auth_type),
        "host": mailbox.host,
        "port": mailbox.port,
        "use_ssl": mailbox.use_ssl,
        "username": mailbox.username,
        "has_password": bool(mailbox.password_enc),
        "oauth_provider": _enum_value(mailbox.oauth_provider) if mailbox.oauth_provider else None,
        "oauth_email": mailbox.oauth_email,
        "smtp_host": mailbox.smtp_host,
        "smtp_port": mailbox.smtp_port,
        "smtp_username": mailbox.smtp_username,
        "linked_client_id": mailbox.linked_client_id,
        "is_active": mailbox.is_active,
        "last_fetched_at": mailbox.last_fetched_at,
        "created_at": mailbox.created_at,
        "updated_at": mailbox.updated_at,
    }


async def _validate_linked_client(
    session: AsyncSession,
    tenant_id: int,
    linked_client_id: int | None,
) -> None:
    if linked_client_id is None:
        return

    client = await session.get(Client, linked_client_id)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Linked client not found",
        )
    if client.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: linked client belongs to a different tenant",
        )


async def _test_connection(mailbox: Mailbox, session: AsyncSession) -> dict:
    started = perf_counter()
    result = await test_connection(mailbox, session)
    if result.get("latency_ms", 0) <= 0:
        result["latency_ms"] = int((perf_counter() - started) * 1000)
    return result


async def _exchange_google_oauth_code(code: str) -> dict:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token_response.raise_for_status()
            token_data = token_response.json()

            profile_response = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
            profile_response.raise_for_status()
            profile_data = profile_response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip() or str(exc)
        raise ValueError(f"Google token exchange failed: {detail}") from exc

    email = (profile_data.get("email") or "").strip().lower()
    if not email:
        raise ValueError("Google OAuth did not return an email address.")

    return {
        "email": email,
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": int(token_data.get("expires_in", 3600)),
    }


async def _exchange_microsoft_oauth_code(code: str) -> dict:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_response = await client.post(
                f"https://login.microsoftonline.com/{settings.microsoft_tenant_id}/oauth2/v2.0/token",
                data={
                    "code": code,
                    "client_id": settings.microsoft_client_id,
                    "client_secret": settings.microsoft_client_secret,
                    "redirect_uri": settings.microsoft_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token_response.raise_for_status()
            token_data = token_response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip() or str(exc)
        raise ValueError(f"Microsoft token exchange failed: {detail}") from exc

    id_token_claims = _decode_jwt_payload(token_data.get("id_token", ""))
    email = (
        id_token_claims.get("preferred_username")
        or id_token_claims.get("email")
        or id_token_claims.get("upn")
        or id_token_claims.get("unique_name")
        or ""
    ).strip().lower()
    if not email:
        raise ValueError("Microsoft OAuth did not return an email address in the ID token.")

    return {
        "email": email,
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": int(token_data.get("expires_in", 3600)),
    }


async def _enforce_mailbox_cap(session: AsyncSession, tenant_id: int) -> None:
    """Block creation of a new mailbox if the tenant is at its max_mailboxes cap.
    Pass-through when the cap is null (unlimited)."""
    from app.models.tenant import Tenant
    tenant_row = await session.execute(
        select(Tenant.max_mailboxes).where(Tenant.id == tenant_id)
    )
    cap = tenant_row.scalar_one_or_none()
    if cap is None:
        return
    active_count = await session.scalar(
        select(func.count(Mailbox.id)).where(
            (Mailbox.tenant_id == tenant_id) & (Mailbox.is_active.is_(True))
        )
    )
    if (active_count or 0) >= cap:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Mailbox limit reached for this tenant ({cap}). "
                "Contact the platform admin to raise the limit."
            ),
        )


async def _upsert_oauth_mailbox(
    session: AsyncSession,
    tenant_id: int,
    provider: OAuthProvider,
    oauth_email: str,
    access_token: str,
    refresh_token: str | None,
    expires_in: int,
) -> Mailbox:
    result = await session.execute(
        select(Mailbox).where(
            (Mailbox.tenant_id == tenant_id)
            & (Mailbox.oauth_provider == provider)
            & (Mailbox.oauth_email == oauth_email)
        )
    )
    mailbox = result.scalar_one_or_none()

    defaults = _oauth_mailbox_defaults(provider)
    token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    default_label = f"{defaults['label_prefix']} - {oauth_email}"

    if mailbox is None:
        # Only enforce the cap on truly new mailboxes — reconnecting an existing
        # OAuth email to refresh tokens doesn't count as a new mailbox.
        await _enforce_mailbox_cap(session, tenant_id)
        mailbox = Mailbox(
            tenant_id=tenant_id,
            label=default_label,
            protocol=defaults["protocol"],
            host=defaults["host"],
            port=defaults["port"],
            use_ssl=True,
            auth_type=MailboxAuthType.oauth2,
            username=oauth_email,
            oauth_provider=provider,
            oauth_email=oauth_email,
            is_active=True,
        )
        session.add(mailbox)
    else:
        mailbox.protocol = defaults["protocol"]
        mailbox.host = defaults["host"]
        mailbox.port = defaults["port"]
        mailbox.use_ssl = True
        mailbox.auth_type = MailboxAuthType.oauth2
        mailbox.username = oauth_email
        mailbox.oauth_provider = provider
        mailbox.oauth_email = oauth_email
        mailbox.is_active = True
        if not mailbox.label:
            mailbox.label = default_label

    mailbox.oauth_access_token_enc = encrypt(access_token)
    if refresh_token:
        mailbox.oauth_refresh_token_enc = encrypt(refresh_token)
    mailbox.oauth_token_expiry = token_expiry

    await session.commit()
    await session.refresh(mailbox)
    return mailbox


@router.get("", response_model=list[MailboxRead])
async def list_tenant_mailboxes(
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_tenant_db),
) -> list[dict]:
    mailboxes = await list_mailboxes(session, current_user.tenant_id)
    return [_mask_mailbox(mailbox) for mailbox in mailboxes]


@router.post("", response_model=MailboxRead, status_code=status.HTTP_201_CREATED)
async def create_tenant_mailbox(
    body: MailboxCreate,
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_tenant_db),
) -> dict:
    await _validate_linked_client(session, current_user.tenant_id, body.linked_client_id)
    await _enforce_mailbox_cap(session, current_user.tenant_id)
    mailbox = await create_mailbox(
        session,
        current_user.tenant_id,
        body.model_dump(exclude_none=True),
    )
    return _mask_mailbox(mailbox)


@router.get("/{mailbox_id}", response_model=MailboxRead)
async def get_tenant_mailbox(
    mailbox_id: int,
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_tenant_db),
) -> dict:
    mailbox = await get_mailbox(session, mailbox_id, current_user.tenant_id)
    if not mailbox:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailbox not found")
    return _mask_mailbox(mailbox)


@router.patch("/{mailbox_id}", response_model=MailboxRead)
async def update_tenant_mailbox(
    mailbox_id: int,
    body: MailboxUpdate,
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_tenant_db),
) -> dict:
    mailbox = await get_mailbox(session, mailbox_id, current_user.tenant_id)
    if not mailbox:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailbox not found")

    updates = body.model_dump(exclude_unset=True)
    if "linked_client_id" in updates:
        await _validate_linked_client(session, current_user.tenant_id, updates.get("linked_client_id"))
    mailbox = await update_mailbox(session, mailbox, updates)
    return _mask_mailbox(mailbox)


@router.delete("/{mailbox_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_mailbox(
    mailbox_id: int,
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_tenant_db),
) -> None:
    mailbox = await get_mailbox(session, mailbox_id, current_user.tenant_id)
    if not mailbox:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailbox not found")
    await delete_mailbox(session, mailbox)


class BulkDeleteMailboxesRequest(PydanticBaseModel):
    mailbox_ids: list[int]


@router.post("/bulk-delete")
async def bulk_delete_mailboxes(
    body: BulkDeleteMailboxesRequest,
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_tenant_db),
) -> dict:
    deleted = 0
    for mailbox_id in body.mailbox_ids:
        mailbox = await get_mailbox(session, mailbox_id, current_user.tenant_id)
        if mailbox:
            await delete_mailbox(session, mailbox)
            deleted += 1
    return {"deleted": deleted}


@router.post("/{mailbox_id}/reset-cursor", status_code=status.HTTP_204_NO_CONTENT)
async def reset_mailbox_cursor(
    mailbox_id: int,
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_tenant_db),
) -> None:
    mailbox = await get_mailbox(session, mailbox_id, current_user.tenant_id)
    if not mailbox:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailbox not found")
    mailbox.last_fetched_at = None
    await session.commit()


@router.post("/{mailbox_id}/test", response_model=ConnectionTestResult)
async def test_mailbox_connection(
    mailbox_id: int,
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_tenant_db),
) -> dict:
    mailbox = await get_mailbox(session, mailbox_id, current_user.tenant_id)
    if not mailbox:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailbox not found")
    return await _test_connection(mailbox, session)


@router.get("/oauth/connect/{provider}", response_model=OAuthConnectResponse)
async def get_oauth_connect_url(
    provider: str,
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
) -> dict:
    if provider == "google":
        if not settings.google_client_id or not settings.google_client_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google OAuth is not configured",
            )
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile https://mail.google.com/ https://www.googleapis.com/auth/gmail.send",
            "access_type": "offline",
            "prompt": "consent",
            "state": _build_oauth_state("google", current_user.tenant_id, current_user.id),
        }
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    elif provider == "microsoft":
        if not settings.microsoft_client_id or not settings.microsoft_client_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Microsoft OAuth is not configured",
            )
        params = {
            "client_id": settings.microsoft_client_id,
            "redirect_uri": settings.microsoft_redirect_uri,
            "response_type": "code",
            "scope": (
                "openid profile email offline_access Mail.Read Mail.Send"
            ),
            "state": _build_oauth_state("microsoft", current_user.tenant_id, current_user.id),
        }
        auth_url = (
            f"https://login.microsoftonline.com/{settings.microsoft_tenant_id}/oauth2/v2.0/authorize?"
            + urlencode(params)
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown OAuth provider: {provider}",
        )

    return {"auth_url": auth_url}


@oauth_router.get("/callback/{provider}", response_class=HTMLResponse)
async def oauth_callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    session: AsyncSession = Depends(get_tenant_db),
) -> HTMLResponse:
    if error:
        message = error_description or error.replace("_", " ")
        return _oauth_popup_response("error", f"{provider.title()} OAuth failed: {message}")

    if not code or not state:
        return _oauth_popup_response("error", "OAuth callback was missing the required code or state.")

    try:
        state_data = _parse_oauth_state(state)
    except ValueError as exc:
        return _oauth_popup_response("error", str(exc))

    if state_data["provider"] != provider:
        return _oauth_popup_response("error", "OAuth callback provider did not match the original request.")

    tenant = await session.get(Tenant, state_data["tenant_id"])
    if not tenant:
        return _oauth_popup_response("error", "Tenant not found for this OAuth callback.")
    if not tenant.ingestion_enabled:
        return _oauth_popup_response("error", "Ingestion is not enabled for this tenant.")

    # Verify the user the state was issued to is still valid in the same
    # tenant. The signature already prevents tampering, so user_id is
    # trustworthy; this check guards against an admin who initiated the
    # flow being deactivated or moved to another tenant before completing.
    initiating_user = await session.get(User, state_data["user_id"])
    if not initiating_user:
        return _oauth_popup_response("error", "The user who started this OAuth flow no longer exists.")
    if not initiating_user.is_active:
        return _oauth_popup_response("error", "The user who started this OAuth flow is no longer active.")
    if initiating_user.tenant_id != tenant.id:
        return _oauth_popup_response("error", "OAuth flow user does not match the tenant on this state.")

    try:
        if provider == OAuthProvider.google.value:
            oauth_data = await _exchange_google_oauth_code(code)
            mailbox = await _upsert_oauth_mailbox(
                session,
                tenant.id,
                OAuthProvider.google,
                oauth_data["email"],
                oauth_data["access_token"],
                oauth_data["refresh_token"],
                oauth_data["expires_in"],
            )
        elif provider == OAuthProvider.microsoft.value:
            oauth_data = await _exchange_microsoft_oauth_code(code)
            mailbox = await _upsert_oauth_mailbox(
                session,
                tenant.id,
                OAuthProvider.microsoft,
                oauth_data["email"],
                oauth_data["access_token"],
                oauth_data["refresh_token"],
                oauth_data["expires_in"],
            )
        else:
            return _oauth_popup_response("error", f"Unknown OAuth provider: {provider}")
    except Exception as exc:
        return _oauth_popup_response("error", f"{provider.title()} OAuth setup failed: {exc}")

    # Attribute the connection to the OAuth initiator (signed state),
    # not to whichever session landed the callback.
    try:
        await record_activity_events(
            session,
            [
                build_activity_event(
                    activity_type="MAILBOX_CONNECTED",
                    visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                    tenant_id=tenant.id,
                    actor_user=initiating_user,
                    entity_type="mailbox",
                    entity_id=mailbox.id,
                    summary=(
                        f"{initiating_user.full_name} connected {provider.title()} mailbox "
                        f"{mailbox.oauth_email}."
                    ),
                    route="/mailboxes",
                    route_params={"mailboxId": mailbox.id},
                    metadata={
                        "provider": provider,
                        "mailbox_email": mailbox.oauth_email,
                    },
                )
            ],
        )
        await session.commit()
    except Exception:
        # Activity logging is best-effort here. The mailbox is already saved;
        # losing the audit event is preferable to failing the whole OAuth
        # flow. The actual mailbox row still records its created_at timestamp.
        await session.rollback()

    return _oauth_popup_response(
        "success",
        f"Connected mailbox for {mailbox.oauth_email}.",
        mailbox_id=mailbox.id,
    )
