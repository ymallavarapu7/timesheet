"""Per-tenant database engine registry.

Resolves a tenant slug to its async SQLAlchemy engine, reading the
control-plane ``tenants`` row to pick the shared DB or an isolated
``acufy_tenant_<slug>`` URL based on ``is_isolated``.

Cutover note: cached engines aren't re-resolved on flip; restart the
process or call ``dispose_all`` after toggling ``is_isolated``.
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


# Cap on live tenant engines; oldest idle is evicted past this.
_MAX_LIVE_ENGINES = 32


class _EngineRecord:
    """AsyncEngine + bound sessionmaker."""

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


# slug -> engine record. OrderedDict for insertion-order LRU eviction.
_registry: "OrderedDict[str, _EngineRecord]" = OrderedDict()
_registry_lock = asyncio.Lock()


def _build_isolated_url(db_name: str, db_host: str | None, db_port: int | None) -> str:
    """Build the asyncpg URL for an isolated tenant DB.

    Reuses shared user/password/scheme; host/port from the control-plane
    row override when present.
    """
    base = urlparse(settings.database_url)
    host = db_host or base.hostname
    port = db_port or base.port or 5432
    userinfo = base.netloc.split("@", 1)[0] if "@" in base.netloc else ""
    netloc = f"{userinfo}@{host}:{port}" if userinfo else f"{host}:{port}"
    return f"{base.scheme}://{netloc}/{db_name}"


async def _resolve_db_url_for_slug(slug: str) -> str:
    """Return the asyncpg URL for the given tenant slug.

    Routes to the isolated DB when ``is_isolated`` and ``db_name`` are set;
    otherwise returns the shared URL. Raises LookupError on unknown slug.
    """
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

    # Half-provisioned tenants stay on the shared DB.
    return settings.database_url


async def get_engine_for_slug(slug: str) -> AsyncEngine:
    """Return (and lazily create) the engine for a tenant slug."""
    if not slug:
        raise ValueError("tenant slug must be a non-empty string")

    async with _registry_lock:
        existing = _registry.get(slug)
        if existing is not None:
            _registry.move_to_end(slug)
            return existing.engine

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

        # Lazy dispose so in-flight queries on the evicted engine still complete.
        if len(_registry) > _MAX_LIVE_ENGINES:
            oldest_slug, oldest_record = _registry.popitem(last=False)
            logger.info(
                "tenant_registry: evicting engine for slug=%s (cap=%s)",
                oldest_slug, _MAX_LIVE_ENGINES,
            )
            asyncio.create_task(oldest_record.engine.dispose())

        return engine


async def get_session_factory_for_slug(slug: str):
    """Return the session_factory for a tenant slug, creating the engine on first hit."""
    if not slug:
        raise ValueError("tenant slug must be a non-empty string")
    async with _registry_lock:
        existing = _registry.get(slug)
        if existing is not None:
            _registry.move_to_end(slug)
            return existing.session_factory
    await get_engine_for_slug(slug)
    return _registry[slug].session_factory


def tenant_session(slug: str):
    """Async-context-manager session bound to the tenant's DB.

    Workers use ``async with tenant_session(slug) as session:``. Routes
    should depend on ``get_tenant_db`` instead.
    """
    if not slug:
        raise ValueError("tenant slug must be a non-empty string")

    class _SessionCM:
        def __init__(self, slug: str):
            self._slug = slug
            self._session = None

        async def __aenter__(self):
            factory = await get_session_factory_for_slug(self._slug)
            self._session = factory()
            await self._session.__aenter__()
            return self._session

        async def __aexit__(self, exc_type, exc, tb):
            if self._session is not None:
                await self._session.__aexit__(exc_type, exc, tb)
                self._session = None

    return _SessionCM(slug)


async def resolve_slug_for_tenant_id(tenant_id: int) -> str:
    """Return the tenant's slug for a numeric id (LookupError if absent)."""
    from app.db_control import AsyncControlSessionLocal
    from app.models.control import ControlTenant

    async with AsyncControlSessionLocal() as session:
        slug = (await session.execute(
            select(ControlTenant.slug).where(ControlTenant.id == tenant_id)
        )).scalar_one_or_none()

    if slug is None:
        raise LookupError(f"tenant id={tenant_id} not found in control plane")
    return slug


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


# Test-only: drop a registered slug without disposing.
def _forget(slug: str) -> Optional[AsyncEngine]:
    record = _registry.pop(slug, None)
    return record.engine if record else None
