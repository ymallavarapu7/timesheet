"""Per-tenant database engine registry (Phase 3.B + 3.C).

Resolves a tenant slug to its async SQLAlchemy engine. The resolver
reads the control-plane ``tenants`` row and routes based on the
``is_isolated`` flag:

  - ``is_isolated=False`` (default): return the shared ``timesheet_db``
    URL. This is the legacy path, still used by every tenant until
    cutover.
  - ``is_isolated=True``: build the per-tenant URL from the row's
    ``db_name`` / ``db_host`` / ``db_port`` (and, eventually,
    encrypted credentials). The URL points at ``acufy_tenant_<slug>``.

Cutover safety: once an engine is cached for a slug, the registry
does not re-resolve it. If you flip ``is_isolated`` for a tenant whose
engine is already cached on a running process, that process will keep
serving the old URL until the engine is evicted (LRU) or the process
restarts. The recommended cutover sequence is:
  1. Run ``scripts/migrate_tenant_data.py <slug>`` so the per-tenant DB
     has fresh data.
  2. Flip ``is_isolated=True`` on the control-plane row.
  3. Roll the API + worker pods (or call ``dispose_all`` if you have
     an admin endpoint for it) to drop cached engines.

Design notes:
- One engine per tenant slug, keyed in an in-process dict.
- LRU-style eviction caps the number of live pools so a tenant blast
  (e.g. a flood of distinct slugs from a misconfigured client) cannot
  exhaust Postgres connections.
- Lookups for unknown slugs raise ``LookupError`` rather than
  silently falling back to the shared DB. The dependency layer
  (``get_tenant_db``) handles the legacy "no slug at all" case.

Lifecycle:
- Engines are created lazily on first ``get_engine_for_slug`` call.
- ``dispose_all`` closes every pool. Called from app shutdown.
- No async work is done at module import time.
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


# Cap on the number of live tenant engines. Past this we evict the
# oldest idle one. Default sized for "small dev fleet"; production
# tunes this via env var alongside PgBouncer config in 3.E.
_MAX_LIVE_ENGINES = 32


class _EngineRecord:
    """Bookkeeping wrapper around an AsyncEngine.

    Holds the engine itself plus a session factory bound to it. We
    keep the factory alongside the engine because session_makers are
    cheap and tying them together avoids the per-request cost of
    re-binding.
    """

    __slots__ = ("engine", "session_factory")

    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self.session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )


# slug -> engine record. OrderedDict so we can evict in insertion
# order when we go over _MAX_LIVE_ENGINES.
_registry: "OrderedDict[str, _EngineRecord]" = OrderedDict()
_registry_lock = asyncio.Lock()


def _build_isolated_url(db_name: str, db_host: str | None, db_port: int | None) -> str:
    """Build the asyncpg URL for an isolated tenant DB.

    Reuses the shared connection's user, password, and scheme. Host
    and port from the control-plane row override the shared values
    when present, so a tenant can be moved to a dedicated cluster by
    editing one row.

    Phase 3.C.2 stores credentials in plaintext on the dev cluster
    (``db_user_enc`` / ``db_password_enc`` are null). When per-tenant
    credentials land, this function gains a decrypt step.
    """
    base = urlparse(settings.database_url)
    host = db_host or base.hostname
    port = db_port or base.port or 5432
    userinfo = base.netloc.split("@", 1)[0] if "@" in base.netloc else ""
    netloc = f"{userinfo}@{host}:{port}" if userinfo else f"{host}:{port}"
    return f"{base.scheme}://{netloc}/{db_name}"


async def _resolve_db_url_for_slug(slug: str) -> str:
    """Return the asyncpg URL for the given tenant slug.

    Reads the control-plane ``tenants`` row. Routes to the per-tenant
    DB when ``is_isolated=True`` and ``db_name`` is set; otherwise
    returns the shared ``settings.database_url``.

    Raises ``LookupError`` if the slug isn't in the control plane --
    callers should treat that as a 404 / 401 rather than masking it
    by silently falling back to the shared DB.
    """
    # Local import keeps the module import-time graph small and avoids
    # an early dependency on the control engine in tests that monkey-
    # patch ``_resolve_db_url_for_slug`` directly.
    from app.db_control import AsyncControlSessionLocal
    from app.models.control import ControlTenant

    async with AsyncControlSessionLocal() as session:
        tenant = (await session.execute(
            select(ControlTenant).where(ControlTenant.slug == slug)
        )).scalar_one_or_none()

    if tenant is None:
        raise LookupError(f"tenant slug={slug!r} not found in control plane")

    if tenant.is_isolated and tenant.db_name:
        return _build_isolated_url(tenant.db_name, tenant.db_host, tenant.db_port)

    # Shared-DB tenants (the default until cutover) and isolated
    # tenants without a db_name (half-provisioned -- the safe
    # behaviour is to keep serving from the shared DB until
    # provisioning completes).
    return settings.database_url


async def get_engine_for_slug(slug: str) -> AsyncEngine:
    """Return (and lazily create) the engine for a tenant slug.

    Thread/coroutine-safe: a single lock guards the registry so two
    concurrent first-hits don't create two engines for the same slug.
    """
    if not slug:
        raise ValueError("tenant slug must be a non-empty string")

    async with _registry_lock:
        existing = _registry.get(slug)
        if existing is not None:
            # LRU bump: move to end so it's the youngest, least-evictable.
            _registry.move_to_end(slug)
            return existing.engine

        # Resolve outside? No -- we still hold the lock so a concurrent
        # first-hit on the same slug doesn't double-resolve. The lookup
        # is one indexed read on the control-plane DB, fast enough that
        # serializing it is fine.
        url = await _resolve_db_url_for_slug(slug)
        is_sqlite = "sqlite" in url
        engine = create_async_engine(
            url,
            echo=False,
            future=True,
            pool_pre_ping=True,
            **({} if is_sqlite else {
                "pool_size": 3,
                "max_overflow": 2,
            }),
        )
        _registry[slug] = _EngineRecord(engine)

        # Evict the oldest if we've blown the cap. Disposes lazily so
        # in-flight queries on the evicted engine still complete.
        if len(_registry) > _MAX_LIVE_ENGINES:
            oldest_slug, oldest_record = _registry.popitem(last=False)
            logger.info(
                "tenant_registry: evicting engine for slug=%s (cap=%s)",
                oldest_slug, _MAX_LIVE_ENGINES,
            )
            asyncio.create_task(oldest_record.engine.dispose())

        return engine


async def get_session_factory_for_slug(slug: str):
    """Return the session_factory for a tenant slug, creating the
    engine on first hit. Returned factory is reusable; callers should
    use it as ``async with factory() as session:``."""
    if not slug:
        raise ValueError("tenant slug must be a non-empty string")
    async with _registry_lock:
        existing = _registry.get(slug)
        if existing is not None:
            _registry.move_to_end(slug)
            return existing.session_factory
    # Engine doesn't exist yet — create it (releases the lock first to
    # avoid double-acquire).
    await get_engine_for_slug(slug)
    return _registry[slug].session_factory


async def dispose_all() -> None:
    """Dispose every registered engine. Idempotent."""
    async with _registry_lock:
        records = list(_registry.values())
        _registry.clear()
    for record in records:
        try:
            await record.engine.dispose()
        except Exception as exc:  # noqa: BLE001 - shutdown best-effort
            logger.warning("tenant_registry: dispose failed: %s", exc)


def registered_slugs() -> list[str]:
    """Snapshot of currently-registered slugs. For diagnostics."""
    return list(_registry.keys())


# Test-only hook: drop a registered slug without disposing. Used in
# integration tests that swap the resolver mid-test.
def _forget(slug: str) -> Optional[AsyncEngine]:
    record = _registry.pop(slug, None)
    return record.engine if record else None
