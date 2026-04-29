"""Tests for the worker-facing helpers in ``app.db_tenant``: the
``tenant_session(slug)`` async context manager and the
``resolve_slug_for_tenant_id(tenant_id)`` reverse lookup.

These are the seams Phase 3.C workers use to bind themselves to a
tenant's database without going through FastAPI's dependency
injection (which workers don't have).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db_tenant import resolve_slug_for_tenant_id, tenant_session
from app.models.control import ControlBase, ControlTenant


@pytest_asyncio.fixture
async def control_factory(tmp_path, monkeypatch):
    db_file = tmp_path / "control.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(ControlBase.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    import app.db_control as db_control
    monkeypatch.setattr(db_control, "AsyncControlSessionLocal", factory)
    yield factory
    await engine.dispose()


def test_tenant_session_rejects_empty_slug():
    """Constructing the helper with an empty slug must fail loudly,
    not lazily on enter. Matches ``get_engine_for_slug``'s contract."""
    with pytest.raises(ValueError):
        tenant_session("")


@pytest.mark.asyncio
async def test_tenant_session_raises_lookup_for_unknown_slug(control_factory):
    """Entering the context for an unknown slug must raise
    ``LookupError``, the same exception ``_resolve_db_url_for_slug``
    raises. Workers turn that into a per-tenant ``failed`` status."""
    with pytest.raises(LookupError):
        async with tenant_session("does-not-exist"):
            pass


@pytest.mark.asyncio
async def test_resolve_slug_for_tenant_id_round_trips(control_factory):
    """Reverse lookup returns the slug for a known tenant id."""
    async with control_factory() as session:
        session.add(ControlTenant(name="Acme", slug="acme-co", id=42))
        await session.commit()

    slug = await resolve_slug_for_tenant_id(42)
    assert slug == "acme-co"


@pytest.mark.asyncio
async def test_resolve_slug_for_tenant_id_raises_for_unknown(control_factory):
    """Unknown tenant id must raise ``LookupError`` so callers can
    surface a clean failure status instead of silently swallowing it."""
    with pytest.raises(LookupError):
        await resolve_slug_for_tenant_id(99999)
