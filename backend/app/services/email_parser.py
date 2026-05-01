"""
Email parsing helpers for raw RFC822 messages.
Extracts normalized headers, body content, and attachment payloads.
"""

import email
import hashlib
import logging
import re
from datetime import datetime, timezone
from email import policy
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)

PROCESSABLE_MIME_TYPES = {
    "application/pdf",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "application/csv",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/tiff",
    "image/bmp",
    "image/gif",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

PROCESSABLE_EXTENSIONS = {
    ".pdf",
    ".xls",
    ".xlsx",
    ".csv",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    ".doc",
    ".docx",
}

SKIP_FILENAME_PATTERNS = {
    "signature",
    "logo",
    "banner",
    "footer",
    "header",
    "icon",
    "avatar",
    "photo",
    "picture",
}
# Note: "image" was intentionally removed from SKIP_FILENAME_PATTERNS.
# Many real timesheets arrive with generic filenames like "image001.png"
# or "image.png". Skipping all files containing "image" in the name
# caused legitimate timesheet attachments to be silently dropped.
# The pipeline's AI classification handles non-timesheet images downstream.

TIMESHEET_FILENAME_KEYWORDS = {
    "timesheet",
    "timesheets",
    "timelog",
    "time_sheet",
    "time-sheet",
    "hours",
    "ts_",
    "_ts",
    "timecard",
    "time_card",
    "week ending",
    "weekly hours",
    "worked hours",
    "consultant hours",
    "billable",
}


def _decode_str(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        # Try chardet detection before falling back to UTF-8
        try:
            import chardet
            detected = chardet.detect(value[:5000])
            if detected and detected.get("encoding") and detected.get("confidence", 0) > 0.5:
                return value.decode(detected["encoding"], errors="replace")
        except (ImportError, Exception):
            pass
        return value.decode("utf-8", errors="replace")

    decoded: list[str] = []
    for part, charset in decode_header(value):
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return "".join(decoded)


def _is_processable_attachment(filename: str, mime_type: str) -> bool:
    normalized_mime = (mime_type or "").lower().strip()
    filename_lower = (filename or "").lower()

    if any(skip in filename_lower for skip in SKIP_FILENAME_PATTERNS):
        return False

    if normalized_mime in PROCESSABLE_MIME_TYPES:
        return True
    return Path(filename_lower).suffix in PROCESSABLE_EXTENSIONS


def _is_likely_timesheet_filename(filename: str) -> bool:
    filename_lower = (filename or "").lower()
    return any(keyword in filename_lower for keyword in TIMESHEET_FILENAME_KEYWORDS)


def _is_timesheet_attachment(filename: str, mime_type: str) -> bool:
    return _is_processable_attachment(filename, mime_type)


class ParsedAttachment(NamedTuple):
    filename: str
    mime_type: str
    content: bytes
    is_processable: bool
    likely_timesheet: bool


class ParsedEmail(NamedTuple):
    message_id: str
    subject: str
    sender_email: str
    sender_name: str
    recipients: list[str]
    body_text: str
    body_html: str
    received_at: datetime | None
    has_attachments: bool
    raw_headers: dict
    attachments: list[ParsedAttachment]
    # Populated only when the email is a recognizable forward AND we can
    # extract the original sender from the forwarded block in the body.
    # Otherwise both are None and callers should use sender_email/name.
    forwarded_from_email: str | None = None
    forwarded_from_name: str | None = None
    # (name, email) pairs from the forward chain; reviewers pick from these
    # when no user matches the outer sender. Tuple default because NamedTuple
    # shares a mutable default across instances.
    chain_senders: tuple[dict, ...] = ()


# Matches the common forward markers Outlook/Gmail/Apple Mail insert.
_FORWARD_MARKERS = (
    "-----forwarded message-----",
    "---------- forwarded message ----------",
    "--------forwarded message--------",
    "begin forwarded message",
    "-------- original message --------",
    "----- original message -----",
    "--------original message--------",
)

# Subject-line forward prefixes (case-insensitive).
_FORWARD_SUBJECT_PREFIXES = ("fwd:", "fw:")


def _subject_looks_forwarded(subject: str) -> bool:
    if not subject:
        return False
    s = subject.strip().lower()
    return any(s.startswith(p) for p in _FORWARD_SUBJECT_PREFIXES)


def _body_has_forward_marker(body: str) -> bool:
    if not body:
        return False
    lower = body.lower()
    return any(marker in lower for marker in _FORWARD_MARKERS)


def _extract_original_sender(body: str) -> tuple[str | None, str | None]:
    """Parse the first 'From:' header line inside a forwarded block.

    Returns (name, email) if a plausible address is found — name may be None.
    Only called when we already know the email is forwarded, so a stray
    'From:' line in signature copy won't falsely trigger here.
    """
    if not body:
        return None, None
    # Scan line-by-line for 'From: ...' — take the first one that parses.
    addr_pattern = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
    name_email_pattern = re.compile(
        r"^\s*From\s*:\s*(?P<rest>.+?)\s*$", re.IGNORECASE
    )
    for raw_line in body.splitlines()[:80]:  # cap scan — forward headers are near the top
        match = name_email_pattern.match(raw_line)
        if not match:
            continue
        rest = match.group("rest").strip()
        # Try "Name <email@x>" first.
        angle = re.match(r"^(?P<name>.+?)\s*<(?P<email>[^>]+)>\s*$", rest)
        if angle:
            email_found = angle.group("email").strip()
            if addr_pattern.fullmatch(email_found):
                name = angle.group("name").strip().strip('"').strip("'") or None
                return name, email_found.lower()
        # Fall back to a bare email with optional surrounding text.
        addr_match = addr_pattern.search(rest)
        if addr_match:
            email_found = addr_match.group(0).lower()
            # Anything before the email (and not the email itself) can serve as name.
            before = rest[: addr_match.start()].strip().strip('"').strip("'")
            name = before or None
            return name, email_found
    return None, None


_CHAIN_SENDERS_CAP = 20


# Matches a "From:" line inside a forwarded body block. Deliberately narrower
# than `_extract_original_sender`'s regex because we scan the WHOLE body here,
# not just the first 80 lines of a confirmed forward — extra context means
# extra false-positive risk. Requires a plausible-looking address to accept.
_CHAIN_FROM_LINE = re.compile(r"^\s*(?:>+\s*)?From\s*:\s*(?P<rest>.+?)\s*$", re.IGNORECASE)
_CHAIN_NAME_EMAIL = re.compile(r"^(?P<name>.+?)\s*<(?P<email>[^>]+)>\s*$")
_CHAIN_BARE_ADDR = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Lines starting with these markers (after any leading '>' quote chars) begin
# a signature block — stop scanning there so we don't collect signature
# blurbs or sent-from-my-phone trailers as fake "senders".
_SIGNATURE_MARKERS = (
    "-- ",           # RFC 3676 standard signature separator
    "--\n",          # Bare "--" on its own line
    "sent from my",  # iPhone/Android auto-sig
    "get outlook for",
    "confidentiality notice",
    "this email and any",
)


def _normalize_chain_entry(name: str | None, email_addr: str | None) -> dict | None:
    """Normalize a (name, email) pair for deduplication and storage."""
    normalized_email = (email_addr or "").strip().lower() or None
    normalized_name = (name or "").strip().strip('"').strip("'") or None
    if not normalized_email and not normalized_name:
        return None
    return {"name": normalized_name, "email": normalized_email}


def _chain_entry_key(entry: dict) -> tuple:
    """Case-insensitive identity used for deduping chain entries."""
    return (
        (entry.get("name") or "").lower(),
        (entry.get("email") or "").lower(),
    )


def _scan_body_for_chain_from_lines(body: str) -> list[dict]:
    """Find every parseable `From: ...` line in the body, skipping signatures."""
    if not body:
        return []
    results: list[dict] = []
    for raw_line in body.splitlines():
        line_lower = raw_line.strip().lower()
        # Strip leading quote markers before checking signature — quoted
        # "Sent from my iPhone" still begins a signature block.
        stripped = raw_line.lstrip("> ").lower()
        if any(stripped.startswith(marker) for marker in _SIGNATURE_MARKERS):
            break
        if line_lower == "--":
            break
        match = _CHAIN_FROM_LINE.match(raw_line)
        if not match:
            continue
        rest = match.group("rest").strip()
        angle = _CHAIN_NAME_EMAIL.match(rest)
        name: str | None = None
        email_addr: str | None = None
        if angle:
            candidate = angle.group("email").strip()
            if _CHAIN_BARE_ADDR.fullmatch(candidate):
                email_addr = candidate
                name = angle.group("name")
        if email_addr is None:
            addr_match = _CHAIN_BARE_ADDR.search(rest)
            if addr_match:
                email_addr = addr_match.group(0)
                before = rest[: addr_match.start()].strip()
                name = before or None
            else:
                # Name-only "From: Jane Doe" — keep it, the reviewer may
                # still recognize the name even without an address.
                name = rest or None
        entry = _normalize_chain_entry(name, email_addr)
        if entry is not None:
            results.append(entry)
    return results


def _scan_nested_rfc822_for_chain(msg) -> list[dict]:
    """
    Collect `From:` from every embedded message/rfc822 part.

    Gmail and Outlook often include the forwarded message as a structured
    MIME part rather than inline body text — when they do, this is the
    most reliable source of chain senders.
    """
    results: list[dict] = []
    try:
        parts = list(msg.walk())
    except Exception:
        return results
    for part in parts:
        try:
            if part.get_content_type() != "message/rfc822":
                continue
            nested = part.get_payload()
            if isinstance(nested, list):
                nested = nested[0] if nested else None
            if nested is None:
                continue
            raw_from = _decode_str(nested.get("From", ""))
            if not raw_from:
                continue
            name, email_addr = _parse_address(raw_from)
            entry = _normalize_chain_entry(name, email_addr)
            if entry is not None:
                results.append(entry)
        except Exception:  # pragma: no cover — defensive only
            continue
    return results


def _is_pure_reply_chain(subject: str, body: str, has_nested_rfc822: bool) -> bool:
    """
    A pure reply chain (Re: threads, no forward markers, no nested RFC822)
    is noise for our purpose — the "senders" in the chain are just the
    same two people bouncing a thread back and forth. Skip extraction.
    """
    if has_nested_rfc822:
        return False
    if _body_has_forward_marker(body):
        return False
    if _subject_looks_forwarded(subject):
        return False
    # If no forward signal at all, but subject looks like a reply, treat
    # as pure reply. If subject is neither reply nor forward, we still
    # scan — sometimes real forwards omit the Fwd: prefix.
    s = (subject or "").strip().lower()
    return s.startswith("re:")


def _extract_chain_senders(msg, subject: str, body: str) -> list[dict]:
    """
    Extract every distinct (name, email) pair we can find in the forward
    chain: nested message/rfc822 parts, plus body-quoted 'From:' lines.

    Returns at most _CHAIN_SENDERS_CAP entries, deduped case-insensitively
    on (name, email). Returns [] for pure reply chains.
    """
    nested = _scan_nested_rfc822_for_chain(msg)
    has_nested = bool(nested)
    if _is_pure_reply_chain(subject, body, has_nested):
        return []
    body_results = _scan_body_for_chain_from_lines(body)

    seen: set[tuple] = set()
    merged: list[dict] = []
    # Nested RFC822 senders come first — they're the most reliable signal.
    for entry in nested + body_results:
        key = _chain_entry_key(entry)
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)
        if len(merged) >= _CHAIN_SENDERS_CAP:
            break
    return merged


def _fallback_message_id(msg, body: str) -> str:
    """Generate a deterministic fallback message ID from sender+subject+date+body[:200]."""
    fingerprint = "|".join([
        msg.get("From", "") or "",
        msg.get("Subject", "") or "",
        msg.get("Date", "") or "",
        body[:200],
    ])
    digest = hashlib.sha256(fingerprint.encode("utf-8", errors="ignore")).hexdigest()
    return f"<generated-{digest}@local>"


def parse_email(raw_bytes: bytes) -> ParsedEmail:
    """Parse raw email bytes into normalized metadata and attachments."""
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)

    message_id = _decode_str(msg.get("Message-ID", "")).strip()
    subject = _decode_str(msg.get("Subject") or msg.get("Thread-Topic") or "")
    sender_name, sender_email = _extract_sender(msg)
    recipients = _parse_recipients(
        [
            _decode_str(msg.get("To", "")),
            _decode_str(msg.get("Cc", "")),
            _decode_str(msg.get("Delivered-To", "")),
        ]
    )

    received_at = None
    date_header = msg.get("Date", "")
    if date_header:
        try:
            received_at = parsedate_to_datetime(date_header)
            if received_at is not None and received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except Exception:
            received_at = None

    raw_headers = {key: _decode_str(value) for key, value in msg.items()}
    body_text = ""
    body_html = ""
    attachments: list[ParsedAttachment] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            if ("attachment" in disposition or "inline" in disposition) and (
                part.get_filename() or part.get_content_maintype() != "text"
            ):
                filename = _decode_str(
                    part.get_filename() or f"attachment.{part.get_content_subtype()}"
                )
                try:
                    content = part.get_payload(decode=True) or b""
                    attachments.append(
                        ParsedAttachment(
                            filename=filename,
                            mime_type=content_type,
                            content=content,
                            is_processable=_is_processable_attachment(filename, content_type),
                            likely_timesheet=_is_likely_timesheet_filename(filename),
                        )
                    )
                except Exception as exc:
                    logger.warning("Failed to extract attachment %s: %s", filename, exc)
                continue

            if content_type == "text/plain" and not body_text:
                body_text = _decode_part_payload(part)
            elif content_type == "text/html" and not body_html:
                body_html = _decode_part_payload(part)
    else:
        payload = _decode_part_payload(msg)
        if msg.get_content_type() == "text/html":
            body_html = payload
        else:
            body_text = payload

    if not body_text and body_html:
        body_text = _strip_html(body_html)

    if not message_id:
        message_id = _fallback_message_id(msg, body_text)

    # Forwarded-email detection (strict): either the subject is prefixed
    # Fwd:/FW: OR the body contains a recognizable forward marker block OR
    # the body holds a parseable 'From:' line we can extract. If any trigger
    # fires AND we can pull an original sender, surface it — otherwise leave
    # both fields None and callers fall back to the outer sender.
    forwarded_from_email: str | None = None
    forwarded_from_name: str | None = None
    subject_is_fwd = _subject_looks_forwarded(subject)
    body_has_marker = _body_has_forward_marker(body_text)
    if subject_is_fwd or body_has_marker:
        forwarded_from_name, forwarded_from_email = _extract_original_sender(body_text)
    if forwarded_from_email is None and forwarded_from_name is None:
        # Third trigger: body has a parseable 'From: ...' line even without
        # explicit markers. Only accept if we successfully extract an address.
        maybe_name, maybe_email = _extract_original_sender(body_text)
        if maybe_email:
            forwarded_from_name, forwarded_from_email = maybe_name, maybe_email

    chain_senders = tuple(_extract_chain_senders(msg, subject, body_text))

    return ParsedEmail(
        message_id=message_id,
        subject=subject,
        sender_email=sender_email,
        sender_name=sender_name,
        recipients=recipients,
        body_text=body_text,
        body_html=body_html,
        received_at=received_at,
        has_attachments=bool(attachments),
        raw_headers=raw_headers,
        attachments=attachments,
        forwarded_from_email=forwarded_from_email,
        forwarded_from_name=forwarded_from_name,
        chain_senders=chain_senders,
    )


def _decode_part_payload(part) -> str:
    try:
        charset = part.get_content_charset()
        payload = part.get_payload(decode=True) or b""
        if not charset:
            # Try to detect charset if not specified in MIME headers
            try:
                import chardet
                detected = chardet.detect(payload[:5000])
                if detected and detected.get("encoding") and detected.get("confidence", 0) > 0.5:
                    charset = detected["encoding"]
                else:
                    charset = "utf-8"
            except ImportError:
                charset = "utf-8"
        return payload.decode(charset, errors="replace")
    except Exception:
        return ""


def _parse_address(raw: str) -> tuple[str, str]:
    from email.utils import parseaddr

    name, address = parseaddr(raw)
    return _decode_str(name), address.lower().strip()


def _parse_recipients(values: list[str] | tuple[str, ...] | str) -> list[str]:
    from email.utils import getaddresses

    if isinstance(values, str):
        values = [values]
    return [address.lower().strip() for _, address in getaddresses(list(values)) if address]


def _extract_sender(msg) -> tuple[str, str]:
    for header_name in ("From", "Sender", "Reply-To", "Return-Path"):
        raw = _decode_str(msg.get(header_name, ""))
        name, address = _parse_address(raw)
        if address:
            return name, address
    return "", ""


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
