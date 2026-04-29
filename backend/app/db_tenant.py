"""Per-tenant database engine registry (Phase 3.B).

Resolves a tenant slug to its async SQLAlchemy engine. In Phase 3.B
every tenant still points at the shared ``timesheet_db`` — the URL
returned by ``_resolve_db_url_for_slug`` is the same for every slug —
but the registry plumbing is in place so Phase 3.C can swap the
resolver to read per-tenant DB URLs from the control plane without
touching any caller.

Design notes:
- One engine per tenant slug, keyed in an in-process dict.
- LRU-style eviction caps the number of live pools so a tenant blast
  (e.g. a flood of distinct slugs from a misconfigured client) cannot
  exhaust Postgres connections.
- The engine for the *current* tenant DB URL is shared with
  ``app/db.py`` to avoid double-pooling against the same database.
  Tenants resolved through the registry that happen to land on the
  same URL get the same engine.

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


def _resolve_db_url_for_slug(slug: str) -> str:
    """Return the asyncpg URL for the given tenant slug.

    Phase 3.B: every tenant lives in the shared ``timesheet_db``, so
    we return ``settings.database_url`` regardless of slug. Phase 3.C
    rewires this to look up the URL in the control-plane ``tenants``
    row's ``db_name`` field (and an encrypted credentials reference).

    Slug parameter is accepted now so 3.C only changes the
    implementation, not callers.
    """
    # Phase 3.C will replace this with a control-plane lookup.
    _ = slug
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

        url = _resolve_db_url_for_slug(slug)
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
