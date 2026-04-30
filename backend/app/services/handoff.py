"""Role handoff: issue + redeem one-time tokens that let a multi-role
user open another portal in a new tab without re-authenticating.

Flow:
    1. The current tab calls POST /auth/role-handoff with a target role
       (which must be in current_user.roles). The endpoint allocates a
       random nonce, stores it in Redis with a 60-second TTL bound to
       (user_id, target_role), and returns a short-lived signed JWT
       carrying the nonce.
    2. The frontend opens the login page in a new browser tab with the
       JWT in the query string. The new tab calls
       POST /auth/role-handoff/exchange. The exchange endpoint
       validates the JWT, atomically pops the nonce from Redis
       (single-use), and mints a fresh access + refresh pair carrying
       the chosen role as the active_role JWT claim. The new tab's
       sessionStorage holds those tokens — independent of the
       originating tab's session.

Why a server-side nonce in addition to the JWT:
    - The JWT travels through the URL bar and stays in browser history.
      Without a server-side nonce, replaying that URL would mint a new
      session for whoever clicked it. The nonce is what we delete on
      redemption to make the token genuinely single-use.
    - The audit log gets exactly one nonce-pop event per successful
      handoff, which is the source of truth for who switched portals.
"""
from __future__ import annotations

import secrets
import logging
from datetime import timedelta
from typing import Optional, Tuple

from app.core.config import settings
from app.core.security import create_access_token, decode_token

logger = logging.getLogger(__name__)


HANDOFF_NONCE_TTL_SECONDS = 60
ROLE_HANDOFF_KEY_PREFIX = "role-handoff:"


def _role_redis_key(nonce: str) -> str:
    return f"{ROLE_HANDOFF_KEY_PREFIX}{nonce}"


async def _redis_client():
    """Lazy import + connect. Mirrors the pattern in api/admin.py so the
    rest of the app keeps working in Redis-less dev environments."""
    import redis.asyncio as aioredis  # type: ignore[import-not-found]
    return aioredis.from_url(settings.redis_url)


async def issue_role_handoff_token(
    *,
    user_id: int,
    target_role: str,
    target_tenant_slug: Optional[str] = None,
) -> str:
    """Allocate a nonce, store it in Redis bound to (user_id, target_role),
    and return a JWT carrying the nonce. Single-use, 60-second TTL."""
    nonce = secrets.token_urlsafe(32)
    payload_value = f"{user_id}:{target_role}"
    client = await _redis_client()
    try:
        await client.setex(
            _role_redis_key(nonce), HANDOFF_NONCE_TTL_SECONDS, payload_value,
        )
    finally:
        await client.aclose()

    jwt_payload = {
        "sub": str(user_id),
        "target_role": target_role,
        "nonce": nonce,
        "kind": "role-handoff",
        "tenant_slug": target_tenant_slug,
    }
    return create_access_token(
        jwt_payload,
        expires_delta=timedelta(seconds=HANDOFF_NONCE_TTL_SECONDS),
    )


async def redeem_role_handoff_token(token: str) -> Tuple[int, str, Optional[str]]:
    """Validate the JWT, atomically pop the nonce, and return
    (user_id, target_role, tenant_slug) on success.

    Raises ValueError on any failure: invalid JWT, expired, missing
    nonce (already redeemed or expired), payload mismatch.
    """
    payload = decode_token(token)
    if not payload:
        raise ValueError("Invalid or expired role-handoff token")
    if payload.get("kind") != "role-handoff":
        raise ValueError("Token is not a role-handoff token")

    nonce = payload.get("nonce")
    user_id = payload.get("sub")
    target_role = payload.get("target_role")

    if not nonce or not user_id or not target_role:
        raise ValueError("Role-handoff token missing required claims")

    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        raise ValueError("Role-handoff token has malformed user id")

    client = await _redis_client()
    try:
        try:
            stored = await client.getdel(_role_redis_key(nonce))
        except AttributeError:
            stored = await client.get(_role_redis_key(nonce))
            if stored is not None:
                await client.delete(_role_redis_key(nonce))
    finally:
        await client.aclose()

    if stored is None:
        raise ValueError("Role-handoff nonce already used or expired")

    expected = f"{user_id_int}:{target_role}".encode()
    stored_bytes = stored if isinstance(stored, (bytes, bytearray)) else str(stored).encode()
    if stored_bytes != expected:
        logger.warning(
            "role-handoff nonce binding mismatch: stored=%r expected=%r",
            stored_bytes, expected,
        )
        raise ValueError("Role-handoff token does not match stored nonce")

    target_tenant_slug = payload.get("tenant_slug")
    return user_id_int, str(target_role), target_tenant_slug
