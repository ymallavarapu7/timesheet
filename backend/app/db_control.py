"""Control-plane database engine and session factory.

The control plane holds cross-tenant data: the tenants directory,
platform-admin accounts, platform settings, and the provisioning audit
log. It lives in its own Postgres database so a bug in tenant routing
cannot leak tenant data into the cross-tenant tables (or vice versa).

Phase 3.A introduces this module alongside the existing `app/db.py`,
which still backs every tenant resource. Phase 3.B+ will add a
per-tenant registry on top of `app/db.py`'s engine pattern.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.models.control import ControlBase  # noqa: F401 — registers tables

_is_sqlite = "sqlite" in settings.control_database_url

control_engine = create_async_engine(
    settings.control_database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    **({} if _is_sqlite else {
        # Smaller pool than the tenant DB — control-plane traffic is
        # rare (login routing, admin pages, provisioning).
        "pool_size": 5,
        "max_overflow": 2,
    }),
)

AsyncControlSessionLocal = async_sessionmaker(
    control_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_control_db():
    """FastAPI dependency that yields a control-plane session.

    Use this dependency on routes that operate on tenants directory,
    platform admins, or platform settings. Tenant data continues to use
    `app.db.get_db`.
    """
    async with AsyncControlSessionLocal() as session:
        yield session


async def close_control_db():
    """Dispose the control-plane engine on shutdown."""
    await control_engine.dispose()
