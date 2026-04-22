"""
Regression guard: every MIME type / file extension the email parser accepts as
a processable attachment MUST have a corresponding dispatch branch in the
extraction pipeline. Drift between the two surfaces is exactly what caused the
silent `.docx` and `.gif` skips — attachments were let through the allowlist,
then hit the extractor's "Unsupported MIME type" fall-through and surfaced as
a misleading `no_structured_timesheet_data` skip reason in the UI.

This test is intentionally coarse: it asserts each allowlisted MIME type is
claimed by some dispatch set, and each allowlisted extension maps via the MIME
normaliser to a claimed MIME type. It doesn't exercise the extractors
themselves — format-specific tests live in other files.
"""
from __future__ import annotations

from app.services.email_parser import (
    PROCESSABLE_EXTENSIONS,
    PROCESSABLE_MIME_TYPES,
)
from app.services.extraction import (
    IMAGE_MIME_TYPES,
    SPREADSHEET_MIME_TYPES,
    WORD_DOC_MIME_TYPES,
    WORD_DOCX_MIME_TYPES,
    _normalize_mime_type,
)

# Every MIME type the extractor knows how to dispatch on. `extract_text` also
# accepts anything matching `"pdf" in mime_type`, so PDF is handled via the
# substring rule, not a set.
_DISPATCHED_MIME_TYPES = (
    SPREADSHEET_MIME_TYPES
    | IMAGE_MIME_TYPES
    | WORD_DOCX_MIME_TYPES
    | WORD_DOC_MIME_TYPES
    | {"application/pdf"}
)


def _is_dispatched(mime: str) -> bool:
    if mime in _DISPATCHED_MIME_TYPES:
        return True
    # Extractor uses substring match for PDF and CSV — mirror that here so a
    # non-standard but accepted MIME (e.g. "application/csv") is still seen as
    # covered.
    if "pdf" in mime or "csv" in mime:
        return True
    return False


def test_every_processable_mime_type_has_extractor_dispatch():
    """
    For every MIME type `email_parser` accepts, the extractor must have a
    dispatch branch. A mismatch here is the exact failure mode we just fixed
    for .docx: attachment accepted → no extractor → misleading skip reason.
    """
    missing = sorted(m for m in PROCESSABLE_MIME_TYPES if not _is_dispatched(m))
    assert not missing, (
        f"The following MIME types are accepted by email_parser but have no "
        f"dispatch branch in extraction.extract_text: {missing}. Either add a "
        f"handler or drop them from PROCESSABLE_MIME_TYPES."
    )


def test_every_processable_extension_normalises_to_dispatched_mime():
    """
    Some mail clients deliver attachments with `application/octet-stream`. The
    extractor falls back on filename suffix via `_normalize_mime_type`. Every
    extension the email parser accepts must map to a dispatched MIME through
    that fallback; otherwise an octet-stream attachment with a known-good
    extension will still hit the "Unsupported MIME type" branch.
    """
    missing: list[tuple[str, str]] = []
    for ext in PROCESSABLE_EXTENSIONS:
        normalised = _normalize_mime_type(f"file{ext}", "application/octet-stream")
        if not _is_dispatched(normalised):
            missing.append((ext, normalised))
    assert not missing, (
        f"The following extensions are accepted by email_parser but the MIME "
        f"normaliser either doesn't map them or maps them to an undispatched "
        f"MIME: {missing}. Add a suffix branch to _normalize_mime_type or a "
        f"set entry to the matching *_MIME_TYPES constant."
    )
