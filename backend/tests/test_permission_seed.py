from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app import models  # noqa: F401
from app.models.base import Base
from app.models.permission import Permission
from app.models.role import Role, RolePermission
from app.models.role_assignment import RoleAssignment
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole
from app.seed_permissions import (
    PERMISSIONS,
    SYSTEM_ROLES,
    _ROLE_INSERT_POSTGRES,
    seed_async,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - shim
    return "JSON"


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    with TemporaryDirectory(dir=REPO_ROOT) as temp_dir:
        db_path = Path(temp_dir) / "permission_seed.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            yield session

        await engine.dispose()


@pytest.mark.asyncio
async def test_all_permission_codes_seeded(db_session: AsyncSession):
    await seed_async(db_session)
    await db_session.commit()

    result = await db_session.execute(select(Permission.code))
    codes = {code for code, in result.all()}

    assert codes == {code for code, _, _ in PERMISSIONS}


@pytest.mark.asyncio
async def test_all_system_roles_seeded(db_session: AsyncSession):
    await seed_async(db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(Role.code, Role.tenant_id).where(Role.tenant_id.is_(None))
    )
    rows = result.all()
    codes = {code for code, _tenant_id in rows}

    assert codes == set(SYSTEM_ROLES.keys())
    assert all(tenant_id is None for _code, tenant_id in rows)


@pytest.mark.asyncio
async def test_role_permission_assignments_correct(db_session: AsyncSession):
    await seed_async(db_session)
    await db_session.commit()

    admin_role = await db_session.scalar(select(Role).where(Role.code == "ADMIN"))
    platform_admin_role = await db_session.scalar(
        select(Role).where(Role.code == "PLATFORM_ADMIN")
    )

    admin_permissions = await db_session.execute(
        select(RolePermission.permission_code).where(
            RolePermission.role_id == admin_role.id
        )
    )
    platform_admin_permissions = await db_session.execute(
        select(RolePermission.permission_code).where(
            RolePermission.role_id == platform_admin_role.id
        )
    )

    admin_codes = set(admin_permissions.scalars().all())
    platform_admin_codes = set(platform_admin_permissions.scalars().all())

    assert "audit.read" in admin_codes
    assert "tenant.create" not in admin_codes
    assert "tenant.create" in platform_admin_codes


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session: AsyncSession):
    tenant = Tenant(name="Seed Tenant", slug="seed-tenant", status=TenantStatus.active)
    user = User(
        tenant=tenant,
        email="seed.employee@example.com",
        username="seed-employee",
        full_name="Seed Employee",
        hashed_password="hashed",
        role=UserRole.EMPLOYEE,
        is_active=True,
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    db_session.add_all([tenant, user])
    await db_session.commit()

    await seed_async(db_session)
    await db_session.commit()
    counts_before = {
        "permissions": await db_session.scalar(select(func.count(Permission.code))),
        "roles": await db_session.scalar(select(func.count(Role.id))),
        "role_permissions": await db_session.scalar(
            select(func.count()).select_from(RolePermission)
        ),
        "role_assignments": await db_session.scalar(
            select(func.count(RoleAssignment.id))
        ),
    }

    await seed_async(db_session)
    await db_session.commit()
    counts_after = {
        "permissions": await db_session.scalar(select(func.count(Permission.code))),
        "roles": await db_session.scalar(select(func.count(Role.id))),
        "role_permissions": await db_session.scalar(
            select(func.count()).select_from(RolePermission)
        ),
        "role_assignments": await db_session.scalar(
            select(func.count(RoleAssignment.id))
        ),
    }

    assert counts_before == counts_after


@pytest.mark.asyncio
async def test_user_role_assignments_seeded(db_session: AsyncSession):
    tenant = Tenant(name="Users Tenant", slug="users-tenant", status=TenantStatus.active)
    user = User(
        tenant=tenant,
        email="employee@example.com",
        username="employee",
        full_name="Employee User",
        hashed_password="hashed",
        role=UserRole.EMPLOYEE,
        is_active=True,
        created_at=datetime(2026, 4, 2, tzinfo=timezone.utc),
    )
    db_session.add_all([tenant, user])
    await db_session.commit()

    await seed_async(db_session)
    await db_session.commit()

    employee_role = await db_session.scalar(select(Role).where(Role.code == "EMPLOYEE"))
    assignment = await db_session.scalar(
        select(RoleAssignment).where(
            RoleAssignment.user_id == user.id,
            RoleAssignment.role_id == employee_role.id,
        )
    )

    assert assignment is not None
    assert assignment.scope_type == "tenant"


def test_role_insert_postgres_uses_distinct_bind_for_where_clause():
    """
    Regression guard for the AmbiguousParameterError that crash-looped the API
    during migration 031 on deploy. asyncpg infers a single type for each
    named parameter used more than once in a statement — reusing `:code` for
    both the INSERT's SELECT list and the NOT EXISTS WHERE comparison made
    the driver see conflicting type hints ("text" vs "character varying") for
    the same $1 placeholder.

    The fix uses distinct bind names (`:code` and `:code_check`) plus explicit
    CASTs. This test asserts the SQL keeps that shape — future edits that
    collapse back to a reused `:code` fail here instead of on a prod server.
    """
    import re

    binds = re.findall(r":(\w+)", _ROLE_INSERT_POSTGRES)
    # INSERT section references :code/:name/:is_system exactly once each;
    # WHERE section uses :code_check. No bind may appear twice — that
    # re-reuse is exactly what asyncpg rejected.
    from collections import Counter

    counts = Counter(binds)
    duplicates = {name: n for name, n in counts.items() if n > 1}
    assert not duplicates, (
        f"Bind parameter(s) reused in _ROLE_INSERT_POSTGRES: {duplicates}. "
        f"asyncpg's AmbiguousParameterError fires when the same bind is "
        f"consumed by columns of different inferred types. Use distinct "
        f"names (e.g. :code vs :code_check) and keep the explicit CASTs."
    )
    # Sanity: the two things we actually care about are both present.
    assert "code" in counts
    assert "code_check" in counts


@pytest.mark.asyncio
async def test_can_review_non_admin_gets_reviewer_assignment(db_session: AsyncSession):
    tenant = Tenant(
        name="Reviewer Tenant",
        slug="reviewer-tenant",
        status=TenantStatus.active,
    )
    user = User(
        tenant=tenant,
        email="reviewer@example.com",
        username="reviewer",
        full_name="Reviewer User",
        hashed_password="hashed",
        role=UserRole.MANAGER,
        can_review=True,
        is_active=True,
        created_at=datetime(2026, 4, 3, tzinfo=timezone.utc),
    )
    db_session.add_all([tenant, user])
    await db_session.commit()

    await seed_async(db_session)
    await db_session.commit()

    reviewer_role = await db_session.scalar(select(Role).where(Role.code == "REVIEWER"))
    assignment = await db_session.scalar(
        select(RoleAssignment).where(
            RoleAssignment.user_id == user.id,
            RoleAssignment.role_id == reviewer_role.id,
        )
    )

    assert assignment is not None
