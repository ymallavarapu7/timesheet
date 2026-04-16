"""
Mailbox fetching service.
Supports IMAP (imapclient) for basic auth / Gmail and Microsoft Graph for Microsoft OAuth.
"""

import asyncio
import base64
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.mailbox import Mailbox, MailboxAuthType, MailboxProtocol, OAuthProvider
from app.services.email_parser import _is_likely_timesheet_filename, _is_processable_attachment
from app.services.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

TOKEN_REFRESH_BUFFER_MINUTES = 5
IMAP_FETCH_BATCH_SIZE = 50
IMAP_OPERATION_TIMEOUT = 120.0  # seconds

# Per-mailbox lock to prevent concurrent OAuth token refreshes
_token_refresh_locks: dict[int, asyncio.Lock] = {}


def _get_refresh_lock(mailbox_id: int) -> asyncio.Lock:
    if mailbox_id not in _token_refresh_locks:
        _token_refresh_locks[mailbox_id] = asyncio.Lock()
    return _token_refresh_locks[mailbox_id]

MICROSOFT_GRAPH_SCOPE = "Mail.Read offline_access"
MICROSOFT_IMAP_SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"


def _microsoft_scope_for_mailbox(mailbox: Mailbox) -> str:
    return (
        MICROSOFT_GRAPH_SCOPE
        if mailbox.protocol == MailboxProtocol.graph
        else MICROSOFT_IMAP_SCOPE
    )


async def _refresh_google_token(mailbox: Mailbox, session: AsyncSession) -> str:
    import httpx

    refresh_token = decrypt(mailbox.oauth_refresh_token_enc or "")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if response.status_code != 200:
            raise ValueError(f"OAuth token refresh failed: {response.status_code} {response.text[:200]}")
        data = response.json()
        if "error" in data:
            raise ValueError(f"OAuth token refresh error: {data.get('error_description', data['error'])}")

    access_token = data["access_token"]
    expires_in = data.get("expires_in", 3600)
    mailbox.oauth_access_token_enc = encrypt(access_token)
    mailbox.oauth_token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    await session.commit()
    return access_token


async def _refresh_microsoft_token(mailbox: Mailbox, session: AsyncSession) -> str:
    import httpx

    refresh_token = decrypt(mailbox.oauth_refresh_token_enc or "")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"https://login.microsoftonline.com/{settings.microsoft_tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": _microsoft_scope_for_mailbox(mailbox),
            },
        )
        if response.status_code != 200:
            raise ValueError(f"OAuth token refresh failed: {response.status_code} {response.text[:200]}")
        data = response.json()
        if "error" in data:
            raise ValueError(f"OAuth token refresh error: {data.get('error_description', data['error'])}")

    access_token = data["access_token"]
    expires_in = data.get("expires_in", 3600)
    mailbox.oauth_access_token_enc = encrypt(access_token)
    if data.get("refresh_token"):
        mailbox.oauth_refresh_token_enc = encrypt(data["refresh_token"])
    mailbox.oauth_token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    await session.commit()
    return access_token


async def _get_fresh_access_token(
    mailbox: Mailbox,
    session: AsyncSession,
    *,
    force_refresh: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    buffer = timedelta(minutes=TOKEN_REFRESH_BUFFER_MINUTES)

    if (
        not force_refresh
        and mailbox.oauth_token_expiry
        and mailbox.oauth_token_expiry > now + buffer
    ):
        return decrypt(mailbox.oauth_access_token_enc or "")

    async with _get_refresh_lock(mailbox.id):
        # Re-check expiry inside lock (double-check pattern) — another coroutine
        # may have already refreshed the token while we waited for the lock.
        now = datetime.now(timezone.utc)
        if (
            not force_refresh
            and mailbox.oauth_token_expiry
            and mailbox.oauth_token_expiry > now + buffer
        ):
            return decrypt(mailbox.oauth_access_token_enc or "")

        logger.info("Refreshing OAuth token for mailbox %s (%s)", mailbox.id, mailbox.oauth_provider)
        if mailbox.oauth_provider == OAuthProvider.google:
            return await _refresh_google_token(mailbox, session)
        if mailbox.oauth_provider == OAuthProvider.microsoft:
            return await _refresh_microsoft_token(mailbox, session)
        raise ValueError(f"Unknown OAuth provider: {mailbox.oauth_provider}")


def _is_auth_failure(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("authenticate", "login", "auth", "credentials", "unauthorized", "401"))


def _should_retry(mailbox: Mailbox, exc: Exception, attempt: int) -> bool:
    """Port of shouldRetryImapAttempt: only OAuth mailboxes, only first attempt, only auth errors."""
    return (
        mailbox.auth_type == MailboxAuthType.oauth2
        and attempt == 0
        and _is_auth_failure(exc)
    )


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip() or None


# ─── Microsoft Graph helpers ─────────────────────────────────────────────────

async def _graph_request(
    access_token: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"https://graph.microsoft.com/v1.0{path}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                **(headers or {}),
            },
        )
        if response.is_error:
            try:
                payload = response.json()
            except Exception:
                payload = response.text
            raise RuntimeError(f"Microsoft Graph request failed: {payload}")
        return response.json()


async def _fetch_graph_attachments(
    access_token: str,
    graph_message_id: str,
) -> list[dict]:
    attachments: list[dict] = []
    attachment_payload = await _graph_request(
        access_token,
        f"/me/messages/{graph_message_id}/attachments?$top=100",
    )
    for attachment in attachment_payload.get("value", []):
        if attachment.get("@odata.type") != "#microsoft.graph.fileAttachment":
            continue
        content_bytes = attachment.get("contentBytes")
        if not content_bytes or attachment.get("isInline"):
            continue

        filename = attachment.get("name") or "attachment"
        mime_type = attachment.get("contentType") or "application/octet-stream"
        content = base64.b64decode(content_bytes)
        attachments.append(
            {
                "filename": filename,
                "mime_type": mime_type,
                "content": content,
                "is_processable": _is_processable_attachment(filename, mime_type),
                "likely_timesheet": _is_likely_timesheet_filename(filename),
            }
        )
    return attachments


async def _normalize_graph_message(
    access_token: str,
    message: dict,
) -> dict:
    attachments: list[dict] = []
    if message.get("hasAttachments"):
        attachments = await _fetch_graph_attachments(access_token, message["id"])

    body = message.get("body") or {}
    body_html = body.get("content") if str(body.get("contentType", "")).lower() == "html" else None
    body_text = (
        message.get("bodyPreview")
        or (body.get("content") if str(body.get("contentType", "")).lower() == "text" else None)
        or _strip_html(body_html)
        or ""
    )

    return {
        "message_id": (message.get("internetMessageId") or message.get("id") or "").strip(),
        "subject": message.get("subject") or "",
        "sender_email": (
            ((message.get("from") or {}).get("emailAddress") or {}).get("address")
            or "unknown@unknown.com"
        ).strip().lower(),
        "sender_name": (((message.get("from") or {}).get("emailAddress") or {}).get("name") or "").strip(),
        "recipients": [
            ((recipient.get("emailAddress") or {}).get("address") or "").strip().lower()
            for recipient in (message.get("toRecipients") or [])
            if ((recipient.get("emailAddress") or {}).get("address") or "").strip()
        ],
        "body_text": body_text,
        "body_html": body_html or "",
        "received_at": message.get("receivedDateTime"),
        "has_attachments": bool(attachments),
        "raw_headers": {},
        "attachments": attachments,
    }


async def _fetch_microsoft_graph_messages(
    mailbox: Mailbox,
    session: AsyncSession,
) -> list[dict]:
    access_token = await _get_fresh_access_token(mailbox, session)
    cutoff = mailbox.last_fetched_at or (datetime.now(timezone.utc) - timedelta(days=30))
    filter_start = (cutoff - timedelta(minutes=5)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    query = (
        "/me/mailFolders/inbox/messages"
        "?$top=50"
        "&$orderby=receivedDateTime desc"
        "&$select=id,internetMessageId,subject,body,bodyPreview,from,toRecipients,receivedDateTime,hasAttachments"
        f"&$filter=receivedDateTime ge {filter_start}"
    )
    payload = await _graph_request(
        access_token,
        query,
        headers={"Prefer": 'outlook.body-content-type="html"'},
    )

    data = payload
    all_messages = data.get("value", [])
    next_link = data.get("@odata.nextLink")
    while next_link and len(all_messages) < 500:  # Safety cap at 500
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=30.0) as _client:
            _resp = await _client.get(
                next_link,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                    "Prefer": 'outlook.body-content-type="html"',
                },
            )
            _resp.raise_for_status()
            data = _resp.json()
        all_messages.extend(data.get("value", []))
        next_link = data.get("@odata.nextLink")

    messages: list[dict] = []
    for message in all_messages:
        messages.append(await _normalize_graph_message(access_token, message))

    return messages


# ─── IMAP message parsing helpers ────────────────────────────────────────────

def _parse_raw_message(raw: bytes) -> dict:
    """
    Parse a raw RFC822 message into a normalized dict.
    Delegates to email_parser.parse_email for canonical RFC822 parsing,
    then converts the result to a plain dict for IMAP callers.
    """
    from app.services.email_parser import parse_email

    parsed = parse_email(raw)

    # Convert received_at to ISO string for consistency with Graph messages
    received_at = None
    if parsed.received_at is not None:
        received_at = parsed.received_at.isoformat()

    # Convert ParsedAttachment NamedTuples to plain dicts
    attachments = [
        {
            "filename": att.filename,
            "mime_type": att.mime_type,
            "content": att.content,
            "is_processable": att.is_processable,
            "likely_timesheet": att.likely_timesheet,
        }
        for att in parsed.attachments
    ]

    return {
        "message_id": parsed.message_id,
        "subject": parsed.subject,
        "sender_email": parsed.sender_email or "unknown@unknown.com",
        "sender_name": parsed.sender_name,
        "recipients": parsed.recipients,
        "body_text": parsed.body_text,
        "body_html": parsed.body_html,
        "received_at": received_at,
        "has_attachments": parsed.has_attachments,
        "raw_headers": parsed.raw_headers,
        "attachments": attachments,
    }


# ─── imapclient synchronous helpers (run in executor) ────────────────────────

def _imap_connect_sync(mailbox: Mailbox, access_token: str | None = None):
    """
    Create and return a connected, authenticated IMAPClient (synchronous).
    Port of imap_service.ts connection logic.
    """
    try:
        from imapclient import IMAPClient
    except ModuleNotFoundError as exc:
        raise RuntimeError("imapclient is required for IMAP fetching.") from exc

    host = mailbox.host
    if not host:
        raise ValueError(f"Mailbox {mailbox.id} has no host configured.")

    port = mailbox.port or (993 if mailbox.use_ssl else 143)
    server = IMAPClient(host, port=port, ssl=mailbox.use_ssl)

    if mailbox.auth_type == MailboxAuthType.basic:
        username = mailbox.username or ""
        password = decrypt(mailbox.password_enc or "")
        server.login(username, password)
    elif mailbox.auth_type == MailboxAuthType.oauth2:
        if access_token is None:
            raise ValueError("OAuth access token required for OAuth2 IMAP login.")
        email_address = (mailbox.oauth_email or mailbox.username or "").strip()
        if not email_address:
            raise ValueError(f"Mailbox {mailbox.id} has no OAuth email configured.")
        server.oauth2_login(email_address, access_token)
    else:
        raise ValueError(f"Unsupported auth type: {mailbox.auth_type}")

    return server


def _fetch_messages_sync(server: Any, last_fetched_at: datetime | None) -> list[dict]:
    """
    Fetch all messages from INBOX (incremental if last_fetched_at is set).
    Port of imap_service.ts fetchMessages.
    """
    try:
        server.select_folder("INBOX")

        if last_fetched_at:
            cutoff = last_fetched_at - timedelta(minutes=5)
            uids = server.search(["SINCE", cutoff.strftime("%d-%b-%Y")])
        else:
            # First fetch: limit to configured window instead of entire inbox
            from app.core.config import settings as app_settings
            cutoff = datetime.now(timezone.utc) - timedelta(days=app_settings.email_fetch_initial_days)
            uids = server.search(["SINCE", cutoff.strftime("%d-%b-%Y")])

        if not uids:
            return []

        messages: list[dict] = []
        for batch_start in range(0, len(uids), IMAP_FETCH_BATCH_SIZE):
            batch_uids = uids[batch_start:batch_start + IMAP_FETCH_BATCH_SIZE]
            batch_data = server.fetch(batch_uids, ["RFC822"])
            for uid, data in batch_data.items():
                raw = data.get(b"RFC822")
                if not raw:
                    continue
                try:
                    parsed = _parse_raw_message(raw)
                    parsed["uid"] = uid
                    messages.append(parsed)
                except Exception as exc:
                    logger.warning("Failed to parse message uid=%s: %s", uid, exc)

        return messages
    finally:
        try:
            server.logout()
        except Exception:
            pass


def _fetch_single_sync(server: Any, search_id: str) -> dict | None:
    """
    Fetch a single message by Message-ID header value (synchronous).
    Port of imap_service.ts testImapConnection / search pattern.
    """
    try:
        server.select_folder("INBOX")
        uids = server.search(["HEADER", "Message-ID", search_id])
        if not uids:
            return None
        fetch_data = server.fetch([uids[0]], ["RFC822"])
        for uid, data in fetch_data.items():
            raw = data.get(b"RFC822")
            if raw:
                parsed = _parse_raw_message(raw)
                parsed["uid"] = uid
                return parsed
        return None
    finally:
        try:
            server.logout()
        except Exception:
            pass


def _test_connection_sync(server: Any) -> int:
    """
    Open INBOX and return message count.
    Port of imap_service.ts testImapConnection — just opens the INBOX lock and releases it.
    """
    try:
        info = server.select_folder("INBOX")
        return int(info.get(b"EXISTS", 0))
    finally:
        try:
            server.logout()
        except Exception:
            pass


# ─── Async IMAP runner with OAuth retry ──────────────────────────────────────

async def _run_imap_operation(
    mailbox: Mailbox,
    session: AsyncSession,
    fn,
    *args,
):
    """
    Run a synchronous IMAP operation in a thread pool executor.
    Retries once with a refreshed token on OAuth authentication failure
    (port of shouldRetryImapAttempt logic from imap_service.ts).
    Applies a per-operation timeout of IMAP_OPERATION_TIMEOUT seconds.
    """
    last_error: Exception | None = None
    for attempt in range(2):
        access_token: str | None = None
        if mailbox.auth_type == MailboxAuthType.oauth2:
            access_token = await _get_fresh_access_token(
                mailbox, session, force_refresh=(attempt > 0)
            )

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda tok=access_token: fn(_imap_connect_sync(mailbox, tok), *args),
                ),
                timeout=IMAP_OPERATION_TIMEOUT,
            )
            return result
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"IMAP operation timed out after {IMAP_OPERATION_TIMEOUT}s "
                f"for mailbox {mailbox.id} ({mailbox.label})"
            )
        except Exception as exc:
            if not _should_retry(mailbox, exc, attempt):
                raise
            logger.info(
                "Mailbox %s: auth failure on attempt %d, retrying with refreshed token: %s",
                mailbox.id,
                attempt,
                exc,
            )
            last_error = exc

    raise last_error  # type: ignore[misc]


# ─── Public API ──────────────────────────────────────────────────────────────

async def fetch_messages(mailbox: Mailbox, session: AsyncSession) -> list[dict]:
    """
    Connect to a mailbox and fetch messages without mutating them.
    Returns normalized message dicts (IMAP or Graph).
    """
    if mailbox.protocol == MailboxProtocol.graph:
        if mailbox.auth_type != MailboxAuthType.oauth2 or mailbox.oauth_provider != OAuthProvider.microsoft:
            raise ValueError("Microsoft Graph mailboxes must use Microsoft OAuth.")
        return await _fetch_microsoft_graph_messages(mailbox, session)

    logger.info("Connecting to mailbox %s (%s) auth=%s", mailbox.id, mailbox.label, mailbox.auth_type)

    last_fetched_at = mailbox.last_fetched_at
    messages: list[dict] = await _run_imap_operation(
        mailbox, session, _fetch_messages_sync, last_fetched_at
    )
    logger.info("Mailbox %s: returning %s parsed messages", mailbox.id, len(messages))
    return messages


async def update_last_fetched_at(mailbox: Mailbox, session: AsyncSession) -> None:
    """
    Update mailbox last_fetched_at cursor after successful processing.

    Callers (e.g. the email_fetch worker) should invoke this AFTER messages
    returned by fetch_messages have been fully processed, so that the cursor
    is not advanced on partial failure.

    Uses a direct UPDATE so it works even when the mailbox instance was loaded
    in a different (now closed) session — the worker's prefetch loop holds
    detached Mailbox objects across multiple sessions.
    """
    from sqlalchemy import update as sa_update
    now = datetime.now(timezone.utc)
    await session.execute(
        sa_update(Mailbox).where(Mailbox.id == mailbox.id).values(last_fetched_at=now)
    )
    # Keep the in-memory object roughly in sync for any caller that reads it.
    mailbox.last_fetched_at = now


async def fetch_single_message(
    mailbox: Mailbox,
    message_id: str,
    session: AsyncSession,
) -> dict | None:
    """Fetch a single email by Message-ID. Used for targeted reprocessing."""
    if mailbox.protocol == MailboxProtocol.graph:
        access_token = await _get_fresh_access_token(mailbox, session)
        escaped_message_id = message_id.replace("'", "''")
        query = (
            "/me/messages"
            "?$top=1"
            "&$select=id,internetMessageId,subject,body,bodyPreview,from,toRecipients,receivedDateTime,hasAttachments"
            f"&$filter=internetMessageId eq '{escaped_message_id}'"
        )
        payload = await _graph_request(
            access_token,
            query,
            headers={"Prefer": 'outlook.body-content-type="html"'},
        )
        matches = payload.get("value") or []
        if not matches and message_id:
            try:
                direct_payload = await _graph_request(
                    access_token,
                    (
                        f"/me/messages/{message_id}"
                        "?$select=id,internetMessageId,subject,body,bodyPreview,from,toRecipients,receivedDateTime,hasAttachments"
                    ),
                    headers={"Prefer": 'outlook.body-content-type="html"'},
                )
                matches = [direct_payload]
            except Exception:
                matches = []

        if not matches:
            return None
        return await _normalize_graph_message(access_token, matches[0])

    if message_id.startswith("<generated-") and message_id.endswith("@local>"):
        return None

    search_id = message_id.strip("<>")
    return await _run_imap_operation(mailbox, session, _fetch_single_sync, search_id)


async def test_connection(mailbox: Mailbox, session: AsyncSession) -> dict:
    """Test mailbox connectivity without advancing fetch cursors."""
    start = datetime.now(timezone.utc)

    try:
        if mailbox.protocol == MailboxProtocol.graph:
            access_token = await _get_fresh_access_token(mailbox, session)
            payload = await _graph_request(
                access_token,
                "/me/mailFolders/inbox?$select=totalItemCount",
            )
            latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
            return {
                "success": True,
                "error": None,
                "latency_ms": latency_ms,
                "message_count": int(payload.get("totalItemCount") or 0),
            }

        message_count: int = await _run_imap_operation(
            mailbox, session, _test_connection_sync
        )
        latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        return {
            "success": True,
            "error": None,
            "latency_ms": latency_ms,
            "message_count": message_count,
        }
    except Exception as exc:
        latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        return {
            "success": False,
            "error": str(exc),
            "latency_ms": latency_ms,
            "message_count": 0,
        }
