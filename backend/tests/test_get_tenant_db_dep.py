"""Tests for the ``get_tenant_db`` FastAPI dependency (Phase 3.C).

The dep resolves the caller's tenant slug and yields a session bound
to that tenant's database. Verifies the resolution order:

  1. ``X-Tenant-Slug`` header (platform-realm tokens only)
  2. ``tenant_slug`` JWT claim (tenant-realm tokens)
  3. Legacy fallback to the shared ``get_db`` when no slug is present

And that an unknown slug becomes a 401, not a 500.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core import deps


def _fake_request(headers: dict[str, str] | None = None):
    """Minimal stand-in for ``fastapi.Request`` -- the dep only reads
    ``request.headers``."""
    return SimpleNamespace(headers=headers or {})


def _fake_credentials(token: str = "irrelevant") -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class _SentinelSession:
    """Marker session so tests can assert which factory yielded."""

    def __init__(self, label: str):
        self.label = label

    async def __aenter__(self) -> "_SentinelSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _make_factory(label: str):
    """Returns an async-context-manager factory that yields a sentinel
    session tagged with ``label``. Mimics ``async_sessionmaker``'s
    callable + context-manager protocol close enough for the dep."""
    @asynccontextmanager
    async def _ctx():
        yield _SentinelSession(label)

    def _factory():
        return _ctx()

    return _factory


@pytest.mark.asyncio
async def test_uses_jwt_claim_for_tenant_realm(monkeypatch):
    """A standard tenant-realm token routes through its
    ``tenant_slug`` claim. Headers are ignored."""
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda _t: {"realm": "tenant", "tenant_slug": "claim-slug"},
    )

    captured: list[str] = []

    async def _fake_get_session_factory(slug: str):
        captured.append(slug)
        return _make_factory(f"session-for-{slug}")

    monkeypatch.setattr(deps, "get_session_factory_for_slug", _fake_get_session_factory)

    gen = deps.get_tenant_db(
        request=_fake_request(headers={"X-Tenant-Slug": "ignored-by-tenant-realm"}),
        credentials=_fake_credentials(),
    )
    session = await gen.__anext__()
    assert session.label == "session-for-claim-slug"
    assert captured == ["claim-slug"]
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()


@pytest.mark.asyncio
async def test_platform_realm_requires_header(monkeypatch):
    """Platform-admin tokens carry ``tenant_id=None`` and must specify
    a tenant via ``X-Tenant-Slug``. A missing header is a 400, not a
    silent fallback to the shared DB."""
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda _t: {"realm": "platform"},
    )

    gen = deps.get_tenant_db(
        request=_fake_request(headers={}),
        credentials=_fake_credentials(),
    )
    with pytest.raises(HTTPException) as exc:
        await gen.__anext__()
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_platform_realm_uses_header_slug(monkeypatch):
    """Platform-admin token + header → routes to the header's slug."""
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda _t: {"realm": "platform"},
    )

    captured: list[str] = []

    async def _fake_get_session_factory(slug: str):
        captured.append(slug)
        return _make_factory(f"session-for-{slug}")

    monkeypatch.setattr(deps, "get_session_factory_for_slug", _fake_get_session_factory)

    gen = deps.get_tenant_db(
        request=_fake_request(headers={"X-Tenant-Slug": "header-slug"}),
        credentials=_fake_credentials(),
    )
    session = await gen.__anext__()
    assert session.label == "session-for-header-slug"
    assert captured == ["header-slug"]


@pytest.mark.asyncio
async def test_falls_back_to_get_db_when_no_slug(monkeypatch):
    """Tokens minted before 3.B don't carry ``tenant_slug``. The dep
    must fall through to the legacy shared session rather than 500."""
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda _t: {"realm": "tenant"},  # no tenant_slug
    )

    fallback_invocations: list[str] = []

    async def _fake_get_db():
        fallback_invocations.append("hit")
        yield _SentinelSession("legacy-shared")

    monkeypatch.setattr(deps, "get_db", _fake_get_db)

    gen = deps.get_tenant_db(
        request=_fake_request(headers={}),
        credentials=_fake_credentials(),
    )
    session = await gen.__anext__()
    assert session.label == "legacy-shared"
    assert fallback_invocations == ["hit"]


@pytest.mark.asyncio
async def test_unknown_slug_becomes_401(monkeypatch):
    """A slug that the resolver can't find must surface as 401, never
    a 500. Stops a typo or stale token from leaking a stack trace."""
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda _t: {"realm": "tenant", "tenant_slug": "ghost"},
    )

    async def _raises(_slug: str):
        raise LookupError("ghost not found")

    monkeypatch.setattr(deps, "get_session_factory_for_slug", _raises)

    gen = deps.get_tenant_db(
        request=_fake_request(),
        credentials=_fake_credentials(),
    )
    with pytest.raises(HTTPException) as exc:
        await gen.__anext__()
    assert exc.value.status_code == 401
    assert "Unknown tenant" in exc.value.detail


@pytest.mark.asyncio
async def test_invalid_token_is_401(monkeypatch):
    """``decode_token`` returning None (bad signature, expired) is a
    401. Falls under the shared ``_decode_or_raise`` helper."""
    monkeypatch.setattr(deps, "decode_token", lambda _t: None)

    gen = deps.get_tenant_db(
        request=_fake_request(),
        credentials=_fake_credentials("bad-token"),
    )
    with pytest.raises(HTTPException) as exc:
        await gen.__anext__()
    assert exc.value.status_code == 401
