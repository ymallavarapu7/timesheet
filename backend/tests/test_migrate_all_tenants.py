"""Tests for the fleet migration runner (Phase 3.E).

The runner shells out to ``alembic upgrade head`` per tenant; we don't
exercise that subprocess here. Instead we cover the surrounding
selection and job-recording logic with a SQLite-backed control plane
and a stubbed alembic step, since that's where the regression risk
lives (skipping unprovisioned tenants, scoping to ``--slug`` flags,
recording a failure row when alembic blows up, etc.).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.control import (
    ControlBase,
    ControlTenant,
    TenantProvisioningJob,
)
from app.models.control.tenant import ControlTenantStatus
from app.models.control.tenant_provisioning_job import (
    ProvisioningJobKind,
    ProvisioningJobStatus,
)
from scripts import migrate_all_tenants as runner


@pytest_asyncio.fixture
async def control_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "control.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(ControlBase.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_tenant(
    *,
    slug: str,
    status: ControlTenantStatus = ControlTenantStatus.active,
    db_name: str | None = None,
) -> ControlTenant:
    return ControlTenant(
        name=slug.title(),
        slug=slug,
        status=status,
        timezone="UTC",
        db_name=db_name,
    )


@pytest.mark.asyncio
async def test_load_targets_skips_unprovisioned_by_default(control_session):
    control_session.add_all([
        _make_tenant(slug="acme", db_name="acufy_tenant_acme"),
        _make_tenant(slug="ghost", db_name=None),
    ])
    await control_session.commit()

    targets = await runner._load_targets(control_session, slugs=None, include_pending=False)
    assert [t.slug for t in targets] == ["acme"]


@pytest.mark.asyncio
async def test_load_targets_include_pending(control_session):
    control_session.add_all([
        _make_tenant(slug="acme", db_name="acufy_tenant_acme"),
        _make_tenant(slug="ghost", db_name=None),
    ])
    await control_session.commit()

    targets = await runner._load_targets(control_session, slugs=None, include_pending=True)
    assert sorted(t.slug for t in targets) == ["acme", "ghost"]


@pytest.mark.asyncio
async def test_load_targets_filters_by_slug(control_session):
    control_session.add_all([
        _make_tenant(slug="acme", db_name="acufy_tenant_acme"),
        _make_tenant(slug="globex", db_name="acufy_tenant_globex"),
    ])
    await control_session.commit()

    targets = await runner._load_targets(
        control_session, slugs=["globex"], include_pending=False
    )
    assert [t.slug for t in targets] == ["globex"]


@pytest.mark.asyncio
async def test_load_targets_skips_inactive(control_session):
    control_session.add_all([
        _make_tenant(slug="acme", db_name="acufy_tenant_acme"),
        _make_tenant(
            slug="suspended-co",
            db_name="acufy_tenant_suspended_co",
            status=ControlTenantStatus.suspended,
        ),
    ])
    await control_session.commit()

    targets = await runner._load_targets(control_session, slugs=None, include_pending=False)
    assert [t.slug for t in targets] == ["acme"]


@pytest.mark.asyncio
async def test_record_and_finish_job_success(control_session):
    tenant = _make_tenant(slug="acme", db_name="acufy_tenant_acme")
    control_session.add(tenant)
    await control_session.commit()

    job = await runner._record_job(control_session, tenant)
    assert job.status == ProvisioningJobStatus.running
    assert job.kind == ProvisioningJobKind.migrate
    assert job.started_at is not None

    await runner._finish_job(control_session, job, revision="038_xyz", error=None)

    fresh = (
        await control_session.execute(
            select(TenantProvisioningJob).where(TenantProvisioningJob.id == job.id)
        )
    ).scalar_one()
    assert fresh.status == ProvisioningJobStatus.succeeded
    assert fresh.alembic_revision == "038_xyz"
    assert fresh.error_message is None
    assert fresh.completed_at is not None


@pytest.mark.asyncio
async def test_finish_job_truncates_long_error(control_session):
    tenant = _make_tenant(slug="acme", db_name="acufy_tenant_acme")
    control_session.add(tenant)
    await control_session.commit()

    job = await runner._record_job(control_session, tenant)
    huge = "x" * 10_000
    await runner._finish_job(control_session, job, revision=None, error=huge)

    fresh = (
        await control_session.execute(
            select(TenantProvisioningJob).where(TenantProvisioningJob.id == job.id)
        )
    ).scalar_one()
    assert fresh.status == ProvisioningJobStatus.failed
    assert fresh.alembic_revision is None
    assert fresh.error_message is not None
    # Truncation guards the audit row from blowing up Postgres tooling.
    assert len(fresh.error_message) == 4000


@pytest.mark.asyncio
async def test_migrate_one_records_failure_when_alembic_raises(
    control_session, monkeypatch
):
    tenant = _make_tenant(slug="acme", db_name="acufy_tenant_acme")
    control_session.add(tenant)
    await control_session.commit()

    def boom(_url):
        raise RuntimeError("alembic exploded")

    monkeypatch.setattr(runner, "_run_alembic_upgrade", boom)

    ok, error = await runner._migrate_one(control_session, tenant)
    assert ok is False
    assert "alembic exploded" in error

    jobs = (
        await control_session.execute(
            select(TenantProvisioningJob).where(
                TenantProvisioningJob.tenant_id == tenant.id
            )
        )
    ).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].status == ProvisioningJobStatus.failed
    assert "alembic exploded" in (jobs[0].error_message or "")


@pytest.mark.asyncio
async def test_migrate_one_succeeds_when_revision_read_fails(
    control_session, monkeypatch
):
    """alembic succeeds, but reading the version_num fails. Job must
    still be marked succeeded with revision=None.
    """
    tenant = _make_tenant(slug="acme", db_name="acufy_tenant_acme")
    control_session.add(tenant)
    await control_session.commit()

    monkeypatch.setattr(runner, "_run_alembic_upgrade", lambda _url: "ok")

    async def fail_read(_url):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(runner, "_read_alembic_revision", fail_read)

    ok, error = await runner._migrate_one(control_session, tenant)
    assert ok is True
    assert error is None

    jobs = (
        await control_session.execute(
            select(TenantProvisioningJob).where(
                TenantProvisioningJob.tenant_id == tenant.id
            )
        )
    ).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].status == ProvisioningJobStatus.succeeded
    assert jobs[0].alembic_revision is None
