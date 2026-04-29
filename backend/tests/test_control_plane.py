"""Tests for the control-plane database (Phase 3.A).

These tests verify the dual-engine setup. They use a SQLite-backed
control engine so the suite runs without a live Postgres. The
fixtures stand up an empty control DB and exercise the four control
models end-to-end.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.control import (
    ControlBase,
    ControlPlatformSettings,
    ControlTenant,
    PlatformAdmin,
    TenantProvisioningJob,
)
from app.models.control.tenant import ControlTenantStatus
from app.models.control.tenant_provisioning_job import (
    ProvisioningJobKind,
    ProvisioningJobStatus,
)


@pytest_asyncio.fixture
async def control_session(tmp_path) -> AsyncSession:
    """Fresh in-process control-plane database for each test."""
    db_file = tmp_path / "control.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(ControlBase.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_control_metadata_only_holds_control_tables():
    """The control-plane base must not pull in tenant tables.

    Regression guard: if a tenant model is accidentally imported on
    ``ControlBase``, this test will see extra tables and fail.
    """
    expected = {
        "tenants",
        "platform_admins",
        "platform_settings",
        "tenant_provisioning_jobs",
    }
    assert set(ControlBase.metadata.tables.keys()) == expected


@pytest.mark.asyncio
async def test_can_insert_and_query_control_tenant(control_session):
    control_session.add(
        ControlTenant(
            name="Acme",
            slug="acme",
            status=ControlTenantStatus.active,
            timezone="UTC",
        )
    )
    await control_session.commit()
    fetched = (
        await control_session.execute(
            ControlTenant.__table__.select().where(ControlTenant.slug == "acme")
        )
    ).first()
    assert fetched is not None
    assert fetched.name == "Acme"


@pytest.mark.asyncio
async def test_platform_admin_round_trip(control_session):
    control_session.add(
        PlatformAdmin(
            email="root@platform.io",
            username="root",
            full_name="Root",
            hashed_password="hash",
            is_active=True,
        )
    )
    await control_session.commit()
    found = (
        await control_session.execute(
            PlatformAdmin.__table__.select().where(PlatformAdmin.email == "root@platform.io")
        )
    ).first()
    assert found is not None


@pytest.mark.asyncio
async def test_platform_settings_unique_key(control_session):
    """``platform_settings.key`` is unique; second insert with the
    same key must raise."""
    control_session.add(ControlPlatformSettings(key="theme", value="dark"))
    await control_session.commit()
    control_session.add(ControlPlatformSettings(key="theme", value="light"))
    with pytest.raises(Exception):
        await control_session.commit()
    await control_session.rollback()


@pytest.mark.asyncio
async def test_tenant_db_connection_columns_default_to_shared(control_session):
    """Phase 3.C.1: a freshly-inserted tenant must default to
    ``is_isolated=False`` and have no connection details set. The
    resolver relies on this to keep new tenants on the shared DB
    until provisioning explicitly flips them over."""
    control_session.add(ControlTenant(name="Fresh", slug="fresh"))
    await control_session.commit()
    fetched = (
        await control_session.execute(
            ControlTenant.__table__.select().where(ControlTenant.slug == "fresh")
        )
    ).first()
    assert fetched.is_isolated is False
    assert fetched.db_name is None
    assert fetched.db_host is None
    assert fetched.db_port is None
    assert fetched.db_user_enc is None
    assert fetched.db_password_enc is None


@pytest.mark.asyncio
async def test_tenant_db_connection_columns_round_trip(control_session):
    """A fully-provisioned tenant carries DB details + is_isolated."""
    control_session.add(ControlTenant(
        name="Provisioned",
        slug="provisioned",
        db_name="acufy_tenant_provisioned",
        db_host="db",
        db_port=5432,
        db_user_enc="enc-user",
        db_password_enc="enc-pw",
        is_isolated=True,
    ))
    await control_session.commit()
    fetched = (
        await control_session.execute(
            ControlTenant.__table__.select().where(ControlTenant.slug == "provisioned")
        )
    ).first()
    assert fetched.is_isolated is True
    assert fetched.db_name == "acufy_tenant_provisioned"
    assert fetched.db_port == 5432


@pytest.mark.asyncio
async def test_provisioning_job_lifecycle(control_session):
    tenant = ControlTenant(name="X", slug="x")
    control_session.add(tenant)
    await control_session.flush()
    job = TenantProvisioningJob(
        tenant_id=tenant.id,
        kind=ProvisioningJobKind.create,
        status=ProvisioningJobStatus.pending,
    )
    control_session.add(job)
    await control_session.commit()

    job.status = ProvisioningJobStatus.succeeded
    job.alembic_revision = "001_initial_control"
    await control_session.commit()

    refetched = (
        await control_session.execute(
            TenantProvisioningJob.__table__.select().where(
                TenantProvisioningJob.id == job.id
            )
        )
    ).first()
    assert refetched.status == ProvisioningJobStatus.succeeded.value
    assert refetched.alembic_revision == "001_initial_control"
