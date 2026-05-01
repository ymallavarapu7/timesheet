"""Tests for the service-token format helpers.

The legacy single-token shape (random 64 chars, bcrypted whole) has
to keep working alongside the new ``<token_id>.<secret>`` shape until
operators have rotated. ``split_service_token`` is the helper that
distinguishes them; the cases below pin its behaviour so a future
edit doesn't regress the legacy path.
"""
from __future__ import annotations

from app.core.security import (
    generate_service_token,
    generate_service_token_id,
    split_service_token,
)


def test_generate_service_token_id_is_16_hex():
    token_id = generate_service_token_id()
    assert len(token_id) == 16
    int(token_id, 16)  # parses as hex


def test_generate_service_token_returns_three_parts():
    public, token_id, secret = generate_service_token()
    assert public == f"{token_id}.{secret}"
    assert len(token_id) == 16
    # url-safe 48-byte secret = 64-char base64-ish string
    assert len(secret) >= 60


def test_split_recognizes_new_format():
    public, token_id, secret = generate_service_token()
    parsed_id, parsed_secret = split_service_token(public)
    assert parsed_id == token_id
    assert parsed_secret == secret


def test_split_treats_legacy_token_as_no_id():
    """Legacy tokens (no dot) come back with token_id=None so the
    caller falls through to the bcrypt-loop path."""
    legacy = "this-is-a-legacy-token-with-no-dot-in-it"
    parsed_id, parsed_secret = split_service_token(legacy)
    assert parsed_id is None
    assert parsed_secret == legacy


def test_split_treats_partial_input_as_legacy():
    """Defensive: a token that's just ``foo.`` or ``.bar`` shouldn't be
    treated as new-format — neither half is meaningful. We fall back
    to the loop path in those cases too."""
    a_id, a_secret = split_service_token("foo.")
    b_id, b_secret = split_service_token(".bar")
    assert a_id is None and a_secret == "foo."
    assert b_id is None and b_secret == ".bar"


def test_split_keeps_extra_dots_in_secret():
    """The secret half might legitimately contain dots (token_urlsafe
    doesn't, but be defensive). Only the first dot is the boundary."""
    parsed_id, parsed_secret = split_service_token("abc123.def.ghi")
    assert parsed_id == "abc123"
    assert parsed_secret == "def.ghi"
