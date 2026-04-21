from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app import models  # noqa: F401
from app.core.permissions import get_user_permissions, shadow_check, user_has_permission
from app.models.base import Base
from app.models.role import Role
from app.models.role_assignment import RoleAssignment
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole
from app.seed_permissions import seed_async


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - shim
    return "JSON"


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    with TemporaryDirectory(dir=REPO_ROOT) as temp_dir:
        db_path = Path(temp_dir) / "permission_checker.db"
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


async def _create_user_with_seed(
    db_session: AsyncSession,
    *,
    role: UserRole,
    email: str,
    username: str,
    can_review: bool = False,
    tenant_required: bool = True,
) -> User:
    tenant = None
    if tenant_required:
        tenant = Tenant(
            name=f"{role.value} Tenant",
            slug=f"{username}-tenant",
            status=TenantStatus.active,
        )
        db_session.add(tenant)
        await db_session.flush()

    user = User(
        tenant=tenant,
        email=email,
        username=username,
        full_name=username.replace("-", " ").title(),
        hashed_password="hashed",
        role=role,
        can_review=can_review,
        is_active=True,
        created_at=datetime(2026, 4, 5, tzinfo=timezone.utc),
    )
    db_session.add(user)
    await db_session.commit()

    await seed_async(db_session)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_get_user_permissions_returns_correct_set_for_employee(
    db_session: AsyncSession,
):
    user = await _create_user_with_seed(
        db_session,
        role=UserRole.EMPLOYEE,
        email="employee.permissions@example.com",
        username="employee-permissions",
    )

    perms = await get_user_permissions(db_session, user)

    assert isinstance(perms, frozenset)
    assert "time_entry.read_own" in perms
    assert "audit.read" not in perms
    assert "tenant.create" not in perms


@pytest.mark.asyncio
async def test_get_user_permissions_returns_correct_set_for_admin(
    db_session: AsyncSession,
):
    user = await _create_user_with_seed(
        db_session,
        role=UserRole.ADMIN,
        email="admin.permissions@example.com",
        username="admin-permissions",
    )

    perms = await get_user_permissions(db_session, user)

    assert "audit.read" in perms
    assert "user.manage" in perms
    assert "time_entry.approve_any" in perms
    assert "tenant.create" not in perms


@pytest.mark.asyncio
async def test_get_user_permissions_returns_correct_set_for_platform_admin(
    db_session: AsyncSession,
):
    user = await _create_user_with_seed(
        db_session,
        role=UserRole.PLATFORM_ADMIN,
        email="platform.permissions@example.com",
        username="platform-permissions",
        tenant_required=False,
    )

    perms = await get_user_permissions(db_session, user)

    assert "tenant.create" in perms
    assert "platform.settings.manage" in perms


@pytest.mark.asyncio
async def test_user_has_permission_true_and_false(db_session: AsyncSession):
    user = await _create_user_with_seed(
        db_session,
        role=UserRole.EMPLOYEE,
        email="employee.hasperm@example.com",
        username="employee-hasperm",
    )

    assert await user_has_permission(db_session, user, "time_entry.read_own") is True
    assert await user_has_permission(db_session, user, "audit.read") is False


@pytest.mark.asyncio
async def test_expired_assignment_not_counted(db_session: AsyncSession):
    tenant = Tenant(name="Expired Tenant", slug="expired-tenant", status=TenantStatus.active)
    user = User(
        tenant=tenant,
        email="expired@example.com",
        username="expired-user",
        full_name="Expired User",
        hashed_password="hashed",
        role=UserRole.EMPLOYEE,
        is_active=True,
        created_at=datetime(2026, 4, 6, tzinfo=timezone.utc),
    )
    db_session.add_all([tenant, user])
    await db_session.commit()

    await seed_async(db_session)
    await db_session.commit()

    await db_session.execute(
        delete(RoleAssignment).where(RoleAssignment.user_id == user.id)
    )
    employee_role = await db_session.scalar(select(Role).where(Role.code == "EMPLOYEE"))
    db_session.add(
        RoleAssignment(
            user_id=user.id,
            role_id=employee_role.id,
            scope_type="tenant",
            scope_ref_id=tenant.id,
            effective_from=date.today() - timedelta(days=10),
            effective_to=date.today() - timedelta(days=1),
        )
    )
    await db_session.commit()

    perms = await get_user_permissions(db_session, user)

    assert perms == frozenset()


@pytest.mark.asyncio
async def test_shadow_check_logs_mismatch_when_disagrees(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
):
    tenant = Tenant(
        name="Mismatch Tenant",
        slug="mismatch-tenant",
        status=TenantStatus.active,
    )
    user = User(
        tenant=tenant,
        email="mismatch@example.com",
        username="mismatch-user",
        full_name="Mismatch User",
        hashed_password="hashed",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add_all([tenant, user])
    await db_session.commit()

    await seed_async(db_session)
    await db_session.commit()
    await db_session.execute(delete(RoleAssignment).where(RoleAssignment.user_id == user.id))
    await db_session.commit()

    with caplog.at_level("WARNING"):
        await shadow_check(
            db_session,
            user,
            "audit.read",
            old_decision=True,
            context="unit-test",
        )

    assert "SHADOW_MISMATCH" in caplog.text


@pytest.mark.asyncio
async def test_shadow_check_does_not_raise_on_db_error():
    class BrokenSession:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("broken execute")

    user = User(
        email="broken@example.com",
        username="broken-user",
        full_name="Broken User",
        hashed_password="hashed",
        role=UserRole.EMPLOYEE,
        is_active=True,
    )
    user.id = 99

    await shadow_check(
        BrokenSession(),
        user,
        "time_entry.read_own",
        old_decision=True,
        context="broken-db",
    )


@pytest.mark.asyncio
async def test_shadow_check_silent_when_agrees(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
):
    user = await _create_user_with_seed(
        db_session,
        role=UserRole.ADMIN,
        email="admin.shadow@example.com",
        username="admin-shadow",
    )

    with caplog.at_level("WARNING"):
        await shadow_check(
            db_session,
            user,
            "audit.read",
            old_decision=True,
            context="agreement",
        )

    assert "SHADOW_MISMATCH" not in caplog.text
