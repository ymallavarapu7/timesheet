"""Unit tests for the role-handoff service.

We mock the Redis client so the suite stays Redis-less. The service
talks to Redis through the small `_redis_client` factory; replacing it
with an in-memory fake exercises the SETEX / GETDEL flow that the real
client uses.
"""
from __future__ import annotations

from typing import Optional

import pytest

from app.services import handoff


class _FakeRedis:
    """Tiny in-memory stand-in supporting setex / getdel / get / delete /
    aclose. Sufficient for the handoff flow's use of Redis."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        # We ignore ttl here; tests don't depend on expiry, only on
        # presence / absence after a getdel.
        self.store[key] = value.encode() if isinstance(value, str) else value

    async def getdel(self, key: str) -> Optional[bytes]:
        return self.store.pop(key, None)

    async def get(self, key: str) -> Optional[bytes]:
        return self.store.get(key)

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()

    async def factory():
        return fake

    monkeypatch.setattr(handoff, "_redis_client", factory)
    return fake


@pytest.mark.asyncio
async def test_role_handoff_round_trip(fake_redis):
    """Issue + redeem must round-trip the (user_id, target_role,
    tenant_slug) triple. The slug is what makes the new tab route
    its DB writes through the per-tenant DB."""
    token = await handoff.issue_role_handoff_token(
        user_id=42,
        target_role="MANAGER",
        target_tenant_slug="acme",
    )
    user_id, role, slug = await handoff.redeem_role_handoff_token(token)
    assert user_id == 42
    assert role == "MANAGER"
    assert slug == "acme"


@pytest.mark.asyncio
async def test_role_handoff_is_single_use(fake_redis):
    token = await handoff.issue_role_handoff_token(
        user_id=42, target_role="ADMIN", target_tenant_slug=None,
    )
    await handoff.redeem_role_handoff_token(token)
    with pytest.raises(ValueError, match="already used or expired"):
        await handoff.redeem_role_handoff_token(token)


@pytest.mark.asyncio
async def test_role_handoff_rejects_garbage_token(fake_redis):
    with pytest.raises(ValueError, match="Invalid"):
        await handoff.redeem_role_handoff_token("not-a-jwt")


@pytest.mark.asyncio
async def test_role_handoff_rejects_token_with_wrong_kind(fake_redis):
    """A normal access token (kind absent) must not redeem here.
    Guards against accidental reuse of a session token as a handoff."""
    from app.core.security import create_access_token
    bogus = create_access_token({"sub": "1", "nonce": "x"})
    with pytest.raises(ValueError, match="not a role-handoff"):
        await handoff.redeem_role_handoff_token(bogus)


@pytest.mark.asyncio
async def test_role_handoff_rejects_when_nonce_was_evicted(fake_redis):
    """Simulate Redis eviction (TTL passed, key gone) between issue and
    redeem. The service must surface that as a clean failure rather
    than a generic crash."""
    token = await handoff.issue_role_handoff_token(
        user_id=42, target_role="MANAGER", target_tenant_slug=None,
    )
    fake_redis.store.clear()
    with pytest.raises(ValueError, match="already used or expired"):
        await handoff.redeem_role_handoff_token(token)


@pytest.mark.asyncio
async def test_role_handoff_rejects_when_jwt_is_tampered(fake_redis):
    """If the JWT carries a different target_role than was stored, the
    binding check must refuse redemption."""
    real_token = await handoff.issue_role_handoff_token(
        user_id=42, target_role="MANAGER", target_tenant_slug=None,
    )
    from app.core.security import decode_token, create_access_token
    payload = decode_token(real_token)
    assert payload is not None
    fake_payload = {
        "sub": str(payload["sub"]),
        "target_role": "ADMIN",  # changed
        "nonce": payload["nonce"],
        "kind": "role-handoff",
    }
    fake_token = create_access_token(fake_payload)
    with pytest.raises(ValueError, match="does not match"):
        await handoff.redeem_role_handoff_token(fake_token)
