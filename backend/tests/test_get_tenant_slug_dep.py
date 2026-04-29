"""Tests for ``get_tenant_slug`` (Phase 3.C).

This dep reads the tenant slug straight from the JWT (or the
``X-Tenant-Slug`` header for platform-realm tokens) so route handlers
can pass the slug into worker enqueue calls without paying a
control-plane lookup later.

The resolution rules mirror ``get_tenant_db`` exactly. These tests
guard against drift between the two so a route that uses both
agrees on which tenant the request is for.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core import deps


def _fake_request(headers: dict[str, str] | None = None):
    return SimpleNamespace(headers=headers or {})


def _fake_credentials(token: str = "irrelevant") -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_returns_jwt_claim_for_tenant_realm(monkeypatch):
    """A tenant-realm token's slug claim is the canonical answer."""
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda _t: {"realm": "tenant", "tenant_slug": "claim-slug"},
    )
    slug = deps.get_tenant_slug(
        request=_fake_request(headers={"X-Tenant-Slug": "ignored"}),
        credentials=_fake_credentials(),
    )
    assert slug == "claim-slug"


def test_platform_realm_requires_header(monkeypatch):
    """Platform-admin tokens carry no tenant_slug claim, so they must
    declare which tenant they are acting on via header. A missing
    header is a 400 -- same contract as ``get_tenant_db``."""
    monkeypatch.setattr(deps, "decode_token", lambda _t: {"realm": "platform"})
    with pytest.raises(HTTPException) as exc:
        deps.get_tenant_slug(
            request=_fake_request(headers={}),
            credentials=_fake_credentials(),
        )
    assert exc.value.status_code == 400


def test_platform_realm_uses_header_slug(monkeypatch):
    monkeypatch.setattr(deps, "decode_token", lambda _t: {"realm": "platform"})
    slug = deps.get_tenant_slug(
        request=_fake_request(headers={"X-Tenant-Slug": "header-slug"}),
        credentials=_fake_credentials(),
    )
    assert slug == "header-slug"


def test_tenant_realm_without_slug_claim_is_403(monkeypatch):
    """Tokens minted before 3.B don't carry tenant_slug. ``get_tenant_db``
    falls through to the legacy shared session in that case; this dep
    can't fall through (slug is the whole return value), so it 403s
    and forces a re-login. Differs from ``get_tenant_db`` deliberately."""
    monkeypatch.setattr(deps, "decode_token", lambda _t: {"realm": "tenant"})
    with pytest.raises(HTTPException) as exc:
        deps.get_tenant_slug(
            request=_fake_request(),
            credentials=_fake_credentials(),
        )
    assert exc.value.status_code == 403


def test_invalid_token_is_401(monkeypatch):
    """``decode_token`` returning None (bad signature, expired) is a
    401 via the shared ``_decode_or_raise`` helper."""
    monkeypatch.setattr(deps, "decode_token", lambda _t: None)
    with pytest.raises(HTTPException) as exc:
        deps.get_tenant_slug(
            request=_fake_request(),
            credentials=_fake_credentials("bad"),
        )
    assert exc.value.status_code == 401
