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
