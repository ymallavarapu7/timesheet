"""Tests for the per-tenant DB URL resolver (Phase 3.C).

Covers ``app.db_tenant._resolve_db_url_for_slug`` and the
``_build_isolated_url`` helper. The resolver reads the control-plane
``tenants`` row to decide whether a tenant is on the shared DB or its
own dedicated database.

These tests stand up an in-process SQLite control DB and monkey-patch
``app.db_control.AsyncControlSessionLocal`` so the resolver hits it
instead of the real Postgres control plane.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db_tenant import _build_isolated_url, _resolve_db_url_for_slug
from app.models.control import ControlBase, ControlTenant


@pytest_asyncio.fixture
async def control_factory(tmp_path, monkeypatch):
    """Stand up an in-process control DB and point the resolver at it.

    Returns the session factory so individual tests can seed rows.
    The monkeypatch swaps the module-level ``AsyncControlSessionLocal``
    that the resolver imports lazily.
    """
    db_file = tmp_path / "control.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(ControlBase.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    # The resolver does ``from app.db_control import AsyncControlSessionLocal``
    # at call time, so we patch the attribute on the module.
    import app.db_control as db_control
    monkeypatch.setattr(db_control, "AsyncControlSessionLocal", factory)
    yield factory
    await engine.dispose()


def test_build_isolated_url_swaps_db_name_and_overrides_host_port():
    """``_build_isolated_url`` must keep the userinfo from the shared
    URL but swap host, port, and database. Production tenants moved
    to a dedicated cluster pass new host/port; same-cluster tenants
    pass None and inherit."""
    # Set a known shared URL so the test is independent of env.
    original = settings.database_url
    try:
        settings.database_url = (
            "postgresql+asyncpg://user:pw@shared.host:5432/timesheet_db"
        )
        # Same cluster (host/port None): inherits userinfo + host + port,
        # only db name swaps.
        url = _build_isolated_url("acufy_tenant_x", None, None)
        assert url == (
            "postgresql+asyncpg://user:pw@shared.host:5432/acufy_tenant_x"
        )
        # Dedicated cluster: host and port override.
        url2 = _build_isolated_url("acufy_tenant_x", "iso.host", 6543)
        assert url2 == (
            "postgresql+asyncpg://user:pw@iso.host:6543/acufy_tenant_x"
        )
    finally:
        settings.database_url = original


@pytest.mark.asyncio
async def test_resolver_raises_for_unknown_slug(control_factory):
    """Unknown slug must raise LookupError, not silently return the
    shared URL. The dependency layer turns this into a 401."""
    with pytest.raises(LookupError):
        await _resolve_db_url_for_slug("does-not-exist")


@pytest.mark.asyncio
async def test_resolver_returns_shared_url_when_not_isolated(control_factory):
    """The default state (``is_isolated=False``) keeps the tenant on
    the shared DB. This is the path every existing tenant takes until
    cutover."""
    async with control_factory() as session:
        session.add(ControlTenant(name="Shared", slug="shared-tenant"))
        await session.commit()

    url = await _resolve_db_url_for_slug("shared-tenant")
    assert url == settings.database_url


@pytest.mark.asyncio
async def test_resolver_returns_per_tenant_url_when_isolated(
    control_factory,
):
    """``is_isolated=True`` plus a populated ``db_name`` routes the
    tenant to its dedicated database."""
    original = settings.database_url
    try:
        settings.database_url = (
            "postgresql+asyncpg://u:p@host:5432/timesheet_db"
        )
        async with control_factory() as session:
            session.add(ControlTenant(
                name="Iso",
                slug="iso-tenant",
                db_name="acufy_tenant_iso_tenant",
                db_host="host",
                db_port=5432,
                is_isolated=True,
            ))
            await session.commit()

        url = await _resolve_db_url_for_slug("iso-tenant")
        assert url == (
            "postgresql+asyncpg://u:p@host:5432/acufy_tenant_iso_tenant"
        )
    finally:
        settings.database_url = original


@pytest.mark.asyncio
async def test_resolver_falls_back_to_shared_when_isolated_but_no_db_name(
    control_factory,
):
    """If a tenant has ``is_isolated=True`` but ``db_name`` is null
    (half-provisioned -- the flag flipped before provisioning
    completed), the resolver must NOT crash. It returns the shared URL
    so the tenant keeps working until provisioning finishes."""
    async with control_factory() as session:
        session.add(ControlTenant(
            name="Half",
            slug="half-provisioned",
            is_isolated=True,
            # db_name deliberately unset
        ))
        await session.commit()

    url = await _resolve_db_url_for_slug("half-provisioned")
    assert url == settings.database_url
