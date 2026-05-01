"""Tests for the attachment storage-key generator.

The original filename is never trusted into the filesystem path: the
on-disk name is a fresh UUID, and the extension is whitelisted to
content types ingestion actually expects to handle. Anything outside
the allowlist (``.php``, ``.html``, ``.svg``, etc.) collapses to
``.bin`` so a malicious sender can't drop active content into our
attachments directory.
"""
from __future__ import annotations

import re

import pytest

from app.services.storage import (
    _ALLOWED_ATTACHMENT_EXTENSIONS,
    _generate_key,
    _safe_extension,
)


_KEY_RE = re.compile(r"^attachments/[0-9a-f]{32}\.[a-z0-9]+$")


@pytest.mark.parametrize("ext", sorted(_ALLOWED_ATTACHMENT_EXTENSIONS))
def test_safe_extension_keeps_allowlisted(ext: str):
    assert _safe_extension(f"timesheet{ext}") == ext


@pytest.mark.parametrize(
    "filename",
    [
        "shell.php",
        "page.html",
        "image.svg",
        "script.js",
        "drop.exe",
        "config.yaml",
        "no_extension_at_all",
        "weird.PhP",  # case mixed
    ],
)
def test_safe_extension_normalizes_unsafe(filename: str):
    assert _safe_extension(filename) == ".bin"


def test_generate_key_shape():
    """Every generated key follows ``attachments/<32-hex>.<ext>``."""
    key = _generate_key("Weekly Timesheet.pdf")
    assert _KEY_RE.match(key), key
    assert key.endswith(".pdf")


def test_generate_key_strips_path_traversal_attempts():
    """Original filename can carry ``../`` segments; the UUID-based
    output must not echo any of that. We don't even use the original
    name as a path component — just its extension — so traversal is
    structurally impossible."""
    key = _generate_key("../../etc/passwd")
    assert ".." not in key
    assert "/" in key  # the literal "attachments/" prefix
    # No extension on /etc/passwd, so the output should be .bin.
    assert key.endswith(".bin")


def test_generate_key_unique_across_calls():
    a = _generate_key("a.pdf")
    b = _generate_key("a.pdf")
    assert a != b


def test_generate_key_normalizes_dangerous_extensions():
    assert _generate_key("payload.php").endswith(".bin")
    assert _generate_key("payload.html").endswith(".bin")
    assert _generate_key("payload.svg").endswith(".bin")
