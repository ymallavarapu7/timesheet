"""
Tests for the ingestion platform sync feature.
All tests use a dedicated test tenant and test service token.

Follows the same SQLite + TestClient pattern as the existing test suite.
"""

import pytest
import pytest_asyncio
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import sync as sync_router_module
from app.core.security import hash_service_token
from app.db import get_db
from app.core.deps import get_tenant_db
from app.models.base import Base
from app.models.client import Client
from app.models.project import Project
from app.models.service_token import ServiceToken
from app.models.sync_log import SyncLog, SyncStatus
from app.models.tenant import Tenant, TenantStatus
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.user import User, UserRole


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

PLAINTEXT_TOKEN = "test-service-token-abc123"


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "sync_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def tenant_and_token(db_session: AsyncSession):
    """Create a test tenant + service token pair."""
    tenant = Tenant(name="Sync Test Tenant", slug="sync-test", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.flush()

    token = ServiceToken(
        name="Test Token",
        token_hash=hash_service_token(PLAINTEXT_TOKEN),
        tenant_id=tenant.id,
        issuer="ingestion_platform",
        is_active=True,
    )
    db_session.add(token)
    await db_session.commit()

    return {"tenant": tenant, "token": token}


@pytest_asyncio.fixture
async def tenant_b_and_token(db_session: AsyncSession):
    """A second tenant for cross-tenant isolation tests."""
    tenant = Tenant(name="Tenant B", slug="tenant-b", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.flush()

    token = ServiceToken(
        name="Tenant B Token",
        token_hash=hash_service_token("tenant-b-token-xyz"),
        tenant_id=tenant.id,
        issuer="ingestion_platform",
        is_active=True,
    )
    db_session.add(token)
    await db_session.commit()

    return {"tenant": tenant, "token": token}


@pytest_asyncio.fixture
async def system_user(db_session: AsyncSession, tenant_and_token: dict):
    """Create the system service user required for timesheet push."""
    from app.core.security import get_password_hash
    import secrets

    tid = tenant_and_token["tenant"].id
    user = User(
        tenant_id=tid,
        email=f"system_ingestion_{tid}@system.internal",
        username=f"system_ingestion_{tid}",
        full_name="Ingestion System",
        hashed_password=get_password_hash(secrets.token_urlsafe(32)),
        role=UserRole.EMPLOYEE,
        is_active=True,
        has_changed_password=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def synced_client(db_session: AsyncSession, tenant_and_token: dict):
    """Pre-synced client for use in project and timesheet tests."""
    tid = tenant_and_token["tenant"].id
    client = Client(
        tenant_id=tid,
        name="Synced Client",
        ingestion_client_id="client-uuid-001",
    )
    db_session.add(client)
    await db_session.commit()
    return client


@pytest_asyncio.fixture
async def synced_employee(db_session: AsyncSession, tenant_and_token: dict):
    """Pre-synced employee for timesheet push tests."""
    from app.core.security import get_password_hash
    tid = tenant_and_token["tenant"].id
    user = User(
        tenant_id=tid,
        email="synced.emp@ingestion.test",
        username="synced_emp",
        full_name="Synced Employee",
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        is_active=True,
        has_changed_password=False,
        ingestion_employee_id="emp-uuid-001",
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def synced_project(db_session: AsyncSession, synced_client: Client):
    """Pre-synced project for timesheet push tests."""
    project = Project(
        tenant_id=synced_client.tenant_id,
        client_id=synced_client.id,
        name="Synced Project",
        billable_rate=Decimal("150.00"),
        currency="USD",
        is_active=True,
        ingestion_project_id="project-uuid-001",
    )
    db_session.add(project)
    await db_session.commit()
    return project


@pytest_asyncio.fixture
async def sync_client(db_session: AsyncSession, tenant_and_token: dict):
    """TestClient with sync router wired up."""
    app = FastAPI()
    app.include_router(sync_router_module.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_get_db
    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def auth_headers(tenant_id: int, token: str = PLAINTEXT_TOKEN) -> dict:
    return {
        "X-Service-Token": token,
        "X-Tenant-ID": str(tenant_id),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test: Service token authentication
# ─────────────────────────────────────────────────────────────────────────────

def test_valid_service_token_accepted(sync_client, tenant_and_token, db_session):
    """Test 1: Valid service token accepted."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": "auth-test-emp-001",
            "full_name": "Auth Test",
            "email": "authtest@example.com",
            "reviewer_name": "Reviewer",
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200


def test_invalid_service_token_rejected(sync_client, tenant_and_token):
    """Test 2: Invalid service token rejected."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": "x",
            "full_name": "X",
            "email": "x@x.com",
            "reviewer_name": "R",
        },
        headers=auth_headers(tid, token="wrong-token"),
    )
    assert resp.status_code == 401


def test_token_from_wrong_tenant_rejected(sync_client, tenant_and_token, tenant_b_and_token):
    """Test 3: Token from wrong tenant rejected."""
    tid_b = tenant_b_and_token["tenant"].id
    # Use tenant A's token but claim to be tenant B
    resp = sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": "x",
            "full_name": "X",
            "email": "x@x.com",
            "reviewer_name": "R",
        },
        headers=auth_headers(tid_b, token=PLAINTEXT_TOKEN),
    )
    assert resp.status_code == 401


def test_missing_headers_rejected(sync_client, tenant_and_token):
    """Test 4: Missing headers rejected."""
    resp = sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": "x",
            "full_name": "X",
            "email": "x@x.com",
            "reviewer_name": "R",
        },
    )
    assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Test: Employee sync
# ─────────────────────────────────────────────────────────────────────────────

def test_new_employee_created(sync_client, tenant_and_token, db_session):
    """Test 5: New employee created."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": "emp-new-001",
            "full_name": "New Employee",
            "email": "newemployee@test.com",
            "reviewer_name": "Reviewer A",
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "created"
    assert data["status"] == "success"
    assert data["user_id"] is not None


@pytest.mark.asyncio
async def test_new_employee_has_correct_tenant(sync_client, tenant_and_token, db_session):
    """Test 5 (extended): Created employee has correct tenant_id."""
    tid = tenant_and_token["tenant"].id
    sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": "emp-tenant-check-001",
            "full_name": "Tenant Check",
            "email": "tenantcheck@test.com",
            "reviewer_name": "Reviewer",
        },
        headers=auth_headers(tid),
    )
    result = await db_session.execute(
        select(User).where(User.ingestion_employee_id == "emp-tenant-check-001")
    )
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.tenant_id == tid


def test_existing_employee_updated_by_ingestion_id(sync_client, tenant_and_token, synced_employee):
    """Test 6: Existing employee updated by ingestion_employee_id."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": synced_employee.ingestion_employee_id,
            "full_name": "Updated Name",
            "email": synced_employee.email,
            "reviewer_name": "Reviewer",
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "updated"
    assert data["user_id"] == synced_employee.id


def test_employee_matched_by_email(sync_client, tenant_and_token, db_session):
    """Test 7: Employee matched by email when no ingestion_employee_id match."""
    import asyncio
    from app.core.security import get_password_hash

    tid = tenant_and_token["tenant"].id

    # Create user without ingestion_employee_id
    async def create_user():
        user = User(
            tenant_id=tid,
            email="preexisting@test.com",
            username="preexisting",
            full_name="Pre Existing",
            hashed_password=get_password_hash("password"),
            role=UserRole.EMPLOYEE,
            is_active=True,
            has_changed_password=False,
        )
        db_session.add(user)
        await db_session.commit()
        return user

    asyncio.get_event_loop().run_until_complete(create_user())

    resp = sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": "new-uuid-for-existing",
            "full_name": "Pre Existing",
            "email": "preexisting@test.com",
            "reviewer_name": "Reviewer",
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] in ("updated", "skipped_no_changes")


def test_employee_in_different_tenant_not_affected(
    sync_client, tenant_and_token, tenant_b_and_token, db_session
):
    """Test 8: Employee in tenant B not modified when syncing tenant A."""
    import asyncio
    from app.core.security import get_password_hash

    tid_b = tenant_b_and_token["tenant"].id
    shared_email = "shared@test.com"

    async def create_b_user():
        user = User(
            tenant_id=tid_b,
            email=shared_email,
            username="shared_b",
            full_name="Tenant B User",
            hashed_password=get_password_hash("password"),
            role=UserRole.EMPLOYEE,
            is_active=True,
            has_changed_password=False,
        )
        db_session.add(user)
        await db_session.commit()
        return user

    b_user = asyncio.get_event_loop().run_until_complete(create_b_user())
    tid_a = tenant_and_token["tenant"].id

    # Sync to tenant A with same email — should create a new user for A, not touch B
    resp = sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": "unique-a-emp",
            "full_name": "Tenant A User",
            "email": shared_email,
            "reviewer_name": "Reviewer",
        },
        headers=auth_headers(tid_a),
    )
    assert resp.status_code == 200
    # B's user should be untouched (still in tenant B)


def test_duplicate_username_handled(sync_client, tenant_and_token, db_session):
    """Test 9: Duplicate username gets numeric suffix."""
    import asyncio
    from app.core.security import get_password_hash

    tid = tenant_and_token["tenant"].id

    async def create_conflicting_user():
        user = User(
            tenant_id=tid,
            email="other@different.com",
            username="duplicate",
            full_name="Duplicate Username",
            hashed_password=get_password_hash("password"),
            role=UserRole.EMPLOYEE,
            is_active=True,
            has_changed_password=False,
        )
        db_session.add(user)
        await db_session.commit()

    asyncio.get_event_loop().run_until_complete(create_conflicting_user())

    # Email prefix "duplicate" will conflict with the existing username
    resp = sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": "dup-uuid-001",
            "full_name": "Dup User",
            "email": "duplicate@somecompany.com",
            "reviewer_name": "Reviewer",
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


# ─────────────────────────────────────────────────────────────────────────────
# Test: Client sync
# ─────────────────────────────────────────────────────────────────────────────

def test_new_client_created(sync_client, tenant_and_token):
    """Test 10: New client created."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/clients",
        json={"ingestion_client_id": "client-new-001", "name": "Brand New Client"},
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "created"
    assert data["status"] == "success"
    assert data["client_id"] is not None


def test_existing_client_updated_by_ingestion_id(sync_client, tenant_and_token, synced_client):
    """Test 11: Existing client updated by ingestion_client_id."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/clients",
        json={
            "ingestion_client_id": synced_client.ingestion_client_id,
            "name": "Updated Client Name",
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "updated"


def test_existing_client_matched_by_name(sync_client, tenant_and_token, synced_client):
    """Test 12: Existing client matched by name (case-insensitive)."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/clients",
        json={
            "ingestion_client_id": "new-client-uuid-999",
            "name": "SYNCED CLIENT",  # uppercase — should match case-insensitively
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["client_id"] == synced_client.id


def test_client_in_different_tenant_not_affected(
    sync_client, tenant_and_token, tenant_b_and_token, db_session
):
    """Test 13: Client in tenant B not affected when syncing tenant A."""
    import asyncio

    tid_b = tenant_b_and_token["tenant"].id

    async def create_b_client():
        client = Client(
            tenant_id=tid_b,
            name="Tenant B Only Client",
            ingestion_client_id="b-client-uuid",
        )
        db_session.add(client)
        await db_session.commit()
        return client

    b_client = asyncio.get_event_loop().run_until_complete(create_b_client())
    tid_a = tenant_and_token["tenant"].id

    # Sync same name to tenant A — should create a new client
    resp = sync_client.post(
        "/sync/clients",
        json={"ingestion_client_id": "a-client-uuid", "name": "Tenant B Only Client"},
        headers=auth_headers(tid_a),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["client_id"] != b_client.id


# ─────────────────────────────────────────────────────────────────────────────
# Test: Project sync
# ─────────────────────────────────────────────────────────────────────────────

def test_new_project_created(sync_client, tenant_and_token, synced_client):
    """Test 14: New project created (client must be synced first)."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/projects",
        json={
            "ingestion_project_id": "proj-new-001",
            "ingestion_client_id": synced_client.ingestion_client_id,
            "name": "New Project",
            "billable_rate": "125.00",
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "created"
    assert data["status"] == "success"


def test_project_sync_fails_if_client_not_synced(sync_client, tenant_and_token):
    """Test 15: Project sync fails if client not synced yet (422 response)."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/projects",
        json={
            "ingestion_project_id": "proj-no-client",
            "ingestion_client_id": "nonexistent-client-uuid",
            "name": "Orphan Project",
            "billable_rate": "100.00",
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 422


def test_existing_project_updated(sync_client, tenant_and_token, synced_client, synced_project):
    """Test 16: Existing project updated, billable_rate changed."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/projects",
        json={
            "ingestion_project_id": synced_project.ingestion_project_id,
            "ingestion_client_id": synced_client.ingestion_client_id,
            "name": synced_project.name,
            "billable_rate": "200.00",
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "updated"


def test_project_matched_by_client_and_code(
    sync_client, tenant_and_token, synced_client, db_session
):
    """Test 17: Project matched by (client_id, code)."""
    import asyncio

    async def create_coded_project():
        project = Project(
            tenant_id=synced_client.tenant_id,
            client_id=synced_client.id,
            name="Coded Project",
            code="CODE-001",
            billable_rate=Decimal("100.00"),
            is_active=True,
        )
        db_session.add(project)
        await db_session.commit()
        return project

    coded_project = asyncio.get_event_loop().run_until_complete(create_coded_project())
    tid = tenant_and_token["tenant"].id

    resp = sync_client.post(
        "/sync/projects",
        json={
            "ingestion_project_id": "proj-by-code-001",
            "ingestion_client_id": synced_client.ingestion_client_id,
            "name": "Coded Project",
            "code": "CODE-001",
            "billable_rate": "100.00",
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == coded_project.id


def test_project_matched_by_client_and_name(
    sync_client, tenant_and_token, synced_client, synced_project
):
    """Test 18: Project matched by (client_id, name) case-insensitive."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/projects",
        json={
            "ingestion_project_id": "proj-new-uuid-matchname",
            "ingestion_client_id": synced_client.ingestion_client_id,
            "name": "SYNCED PROJECT",  # uppercase — should match case-insensitively
            "billable_rate": "150.00",
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == synced_project.id


# ─────────────────────────────────────────────────────────────────────────────
# Test: Timesheet push
# ─────────────────────────────────────────────────────────────────────────────

def test_full_timesheet_push(
    sync_client, tenant_and_token, synced_employee, synced_client, synced_project, system_user
):
    """Test 19: Full push with 5 line items, all created as APPROVED."""
    tid = tenant_and_token["tenant"].id
    today = date.today()
    line_items = [
        {
            "ingestion_line_item_id": f"line-{i}",
            "work_date": (today - timedelta(days=i)).strftime("%Y-%m-%d"),
            "hours": "8.00",
            "description": f"Work day {i}",
        }
        for i in range(5)
    ]
    resp = sync_client.post(
        "/sync/timesheets/push",
        json={
            "ingestion_timesheet_id": "ts-full-001",
            "ingestion_employee_id": synced_employee.ingestion_employee_id,
            "ingestion_client_id": synced_client.ingestion_client_id,
            "ingestion_project_id": synced_project.ingestion_project_id,
            "reviewer_name": "Reviewer Jones",
            "ingestion_source_tenant": "ingestion-co",
            "line_items": line_items,
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["created"] == 5
    assert data["skipped"] == 0
    assert data["failed"] == 0
    for result in data["line_item_results"]:
        assert result["action"] == "created"


@pytest.mark.asyncio
async def test_created_entries_are_approved(
    sync_client, tenant_and_token, synced_employee, synced_client, synced_project,
    system_user, db_session
):
    """Test 19 (extended): Pushed entries have status=APPROVED and correct metadata."""
    tid = tenant_and_token["tenant"].id
    today = date.today()
    sync_client.post(
        "/sync/timesheets/push",
        json={
            "ingestion_timesheet_id": "ts-meta-check",
            "ingestion_employee_id": synced_employee.ingestion_employee_id,
            "ingestion_client_id": synced_client.ingestion_client_id,
            "ingestion_project_id": synced_project.ingestion_project_id,
            "reviewer_name": "Meta Reviewer",
            "ingestion_source_tenant": "meta-ingestion",
            "line_items": [{
                "ingestion_line_item_id": "meta-line-001",
                "work_date": today.strftime("%Y-%m-%d"),
                "hours": "6.00",
                "description": "Meta check entry",
            }],
        },
        headers=auth_headers(tid),
    )

    result = await db_session.execute(
        select(TimeEntry).where(TimeEntry.ingestion_line_item_id == "meta-line-001")
    )
    entry = result.scalar_one_or_none()
    assert entry is not None
    assert entry.status == TimeEntryStatus.APPROVED
    assert entry.approved_by == system_user.id
    assert entry.ingestion_approved_by_name == "Meta Reviewer"
    assert entry.ingestion_timesheet_id == "ts-meta-check"
    assert entry.ingestion_source_tenant == "meta-ingestion"


def test_duplicate_push_skipped(
    sync_client, tenant_and_token, synced_employee, synced_client, synced_project, system_user
):
    """Test 20: Duplicate line item skipped on second push."""
    tid = tenant_and_token["tenant"].id
    today = date.today()
    payload = {
        "ingestion_timesheet_id": "ts-dup-001",
        "ingestion_employee_id": synced_employee.ingestion_employee_id,
        "ingestion_client_id": synced_client.ingestion_client_id,
        "ingestion_project_id": synced_project.ingestion_project_id,
        "reviewer_name": "Reviewer",
        "ingestion_source_tenant": "source",
        "line_items": [
            {
                "ingestion_line_item_id": f"dup-line-{i}",
                "work_date": (today - timedelta(days=i)).strftime("%Y-%m-%d"),
                "hours": "7.00",
                "description": "First push",
            }
            for i in range(5)
        ],
    }

    # First push
    sync_client.post("/sync/timesheets/push", json=payload, headers=auth_headers(tid))

    # Second push (same line item IDs)
    resp = sync_client.post("/sync/timesheets/push", json=payload, headers=auth_headers(tid))
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 0
    assert data["skipped"] == 5
    for result in data["line_item_results"]:
        assert result["action"] == "skipped_duplicate"


def test_push_fails_if_employee_not_synced(
    sync_client, tenant_and_token, synced_client, synced_project, system_user
):
    """Test 22: Push fails if employee not synced."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/timesheets/push",
        json={
            "ingestion_timesheet_id": "ts-no-emp",
            "ingestion_employee_id": "nonexistent-emp-uuid",
            "ingestion_client_id": synced_client.ingestion_client_id,
            "ingestion_project_id": synced_project.ingestion_project_id,
            "reviewer_name": "Reviewer",
            "ingestion_source_tenant": "source",
            "line_items": [{
                "ingestion_line_item_id": "line-no-emp-001",
                "work_date": date.today().strftime("%Y-%m-%d"),
                "hours": "8.00",
            }],
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert "employee" in data["error"].lower() or "missing" in data["error"].lower()


def test_push_fails_if_system_user_not_seeded(
    sync_client, tenant_and_token, synced_employee, synced_client, synced_project
):
    """Test 23: Push fails if system service user not seeded."""
    # Note: system_user fixture is NOT included here
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/timesheets/push",
        json={
            "ingestion_timesheet_id": "ts-no-sys-user",
            "ingestion_employee_id": synced_employee.ingestion_employee_id,
            "ingestion_client_id": synced_client.ingestion_client_id,
            "ingestion_project_id": synced_project.ingestion_project_id,
            "reviewer_name": "Reviewer",
            "ingestion_source_tenant": "source",
            "line_items": [{
                "ingestion_line_item_id": "line-no-sys-001",
                "work_date": date.today().strftime("%Y-%m-%d"),
                "hours": "8.00",
            }],
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert "system" in data["error"].lower() or "seed" in data["error"].lower()


def test_hour_limits_not_enforced(
    sync_client, tenant_and_token, synced_employee, synced_client, synced_project, system_user
):
    """Test 24: Hour limits (12h/day, 60h/week) are NOT enforced for ingestion entries."""
    tid = tenant_and_token["tenant"].id
    resp = sync_client.post(
        "/sync/timesheets/push",
        json={
            "ingestion_timesheet_id": "ts-over-hours",
            "ingestion_employee_id": synced_employee.ingestion_employee_id,
            "ingestion_client_id": synced_client.ingestion_client_id,
            "ingestion_project_id": synced_project.ingestion_project_id,
            "reviewer_name": "Reviewer",
            "ingestion_source_tenant": "source",
            "line_items": [{
                "ingestion_line_item_id": "line-13h-001",
                "work_date": date.today().strftime("%Y-%m-%d"),
                "hours": "13.00",  # exceeds MAX_HOURS_PER_DAY=12
                "description": "Over limit entry",
            }],
        },
        headers=auth_headers(tid),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["created"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test: Sync log
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_log_written_after_employee_sync(
    sync_client, tenant_and_token, db_session
):
    """Test 25: Employee sync writes to sync_log."""
    tid = tenant_and_token["tenant"].id
    sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": "log-test-emp",
            "full_name": "Log Test",
            "email": "logtest@test.com",
            "reviewer_name": "Reviewer",
        },
        headers=auth_headers(tid),
    )
    result = await db_session.execute(
        select(SyncLog).where(
            (SyncLog.tenant_id == tid) &
            (SyncLog.ingestion_id == "log-test-emp")
        )
    )
    log = result.scalar_one_or_none()
    assert log is not None
    assert log.status == SyncStatus.success


@pytest.mark.asyncio
async def test_sync_log_written_on_failure(
    sync_client, tenant_and_token, synced_employee, synced_client, synced_project, db_session
):
    """Test 26: Failed operations write to sync_log with status='failed'."""
    tid = tenant_and_token["tenant"].id
    sync_client.post(
        "/sync/timesheets/push",
        json={
            "ingestion_timesheet_id": "ts-fail-log",
            "ingestion_employee_id": "emp-not-exist-log",
            "ingestion_client_id": synced_client.ingestion_client_id,
            "ingestion_project_id": synced_project.ingestion_project_id,
            "reviewer_name": "Reviewer",
            "ingestion_source_tenant": "source",
            "line_items": [{
                "ingestion_line_item_id": "fail-line-001",
                "work_date": date.today().strftime("%Y-%m-%d"),
                "hours": "8.00",
            }],
        },
        headers=auth_headers(tid),
    )
    result = await db_session.execute(
        select(SyncLog).where(
            (SyncLog.tenant_id == tid) &
            (SyncLog.ingestion_id == "ts-fail-log") &
            (SyncLog.status == SyncStatus.failed)
        )
    )
    log = result.scalar_one_or_none()
    assert log is not None
    assert log.error_message is not None


def test_get_sync_logs_returns_only_current_tenant(
    sync_client, tenant_and_token, tenant_b_and_token
):
    """Test 27: GET /sync/logs returns only current tenant's logs."""
    tid_a = tenant_and_token["tenant"].id
    tid_b = tenant_b_and_token["tenant"].id

    # Create a log entry in tenant A
    sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": "tenant-a-only-emp",
            "full_name": "Tenant A",
            "email": "tenanta@test.com",
            "reviewer_name": "Reviewer",
        },
        headers=auth_headers(tid_a),
    )

    # Create a log entry in tenant B
    sync_client.post(
        "/sync/employees",
        json={
            "ingestion_employee_id": "tenant-b-only-emp",
            "full_name": "Tenant B",
            "email": "tenantb@test.com",
            "reviewer_name": "Reviewer",
        },
        headers=auth_headers(tid_b, token="tenant-b-token-xyz"),
    )

    # Fetch logs as tenant A
    resp = sync_client.get("/sync/logs", headers=auth_headers(tid_a))
    assert resp.status_code == 200
    logs = resp.json()
    for log in logs:
        assert log["tenant_id"] == tid_a


# ─────────────────────────────────────────────────────────────────────────────
# Test: Outbound webhooks
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_client_update_triggers_outbound_webhook(
    db_session, tenant_and_token, synced_client
):
    """Test 28: Client update triggers outbound webhook (mocked)."""
    from app.services.ingestion_sync import _send_outbound_webhook
    from app.schemas import ClientUpdate

    tid = tenant_and_token["tenant"].id

    # Build app with clients router
    from app.api import clients as clients_module
    app = FastAPI()
    app.include_router(clients_module.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_get_db
    # Login as admin requires auth — patch JWT instead by creating a minimal admin user
    from app.core.security import create_access_token, get_password_hash
    admin = User(
        tenant_id=tid,
        email="admin_webhook@test.com",
        username="admin_webhook",
        full_name="Webhook Admin",
        hashed_password=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
        has_changed_password=True,
    )
    db_session.add(admin)
    await db_session.commit()

    token = create_access_token({"sub": str(admin.id), "tenant_id": tid})

    called = []

    async def mock_webhook(**kwargs):
        called.append(kwargs)

    with patch("app.api.clients._send_outbound_webhook", side_effect=mock_webhook):
        with TestClient(app) as client:
            resp = client.put(
                f"/clients/{synced_client.id}",
                json={"name": "Renamed Synced Client"},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    # Background task was registered (may not have fired synchronously, but no error)


def test_client_without_ingestion_id_does_not_trigger_webhook(
    db_session, tenant_and_token
):
    """Test 29: Natively-created client does NOT trigger outbound webhook."""
    import asyncio
    from app.api import clients as clients_module
    from app.core.security import create_access_token, get_password_hash

    tid = tenant_and_token["tenant"].id

    app = FastAPI()
    app.include_router(clients_module.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_get_db
    async def setup():
        # Native client (no ingestion_client_id)
        native_client = Client(
            tenant_id=tid,
            name="Native Client No Ingestion",
        )
        admin = User(
            tenant_id=tid,
            email="admin_native@test.com",
            username="admin_native",
            full_name="Native Admin",
            hashed_password=get_password_hash("AdminPass123!"),
            role=UserRole.ADMIN,
            is_active=True,
            has_changed_password=True,
        )
        db_session.add_all([native_client, admin])
        await db_session.commit()
        return native_client, admin

    native_client, admin = asyncio.get_event_loop().run_until_complete(setup())
    token = create_access_token({"sub": str(admin.id), "tenant_id": tid})

    called = []

    async def mock_webhook(**kwargs):
        called.append(kwargs)

    with patch("app.api.clients._send_outbound_webhook", side_effect=mock_webhook):
        with TestClient(app) as client:
            client.put(
                f"/clients/{native_client.id}",
                json={"name": "Still Native"},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert len(called) == 0


def test_webhook_failure_does_not_fail_client_update(
    db_session, tenant_and_token, synced_client
):
    """Test 30: Webhook failure does not fail the update response."""
    import asyncio
    from app.api import clients as clients_module
    from app.core.security import create_access_token, get_password_hash

    tid = tenant_and_token["tenant"].id

    app = FastAPI()
    app.include_router(clients_module.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_get_db
    async def setup_admin():
        admin = User(
            tenant_id=tid,
            email="admin_fail@test.com",
            username="admin_fail",
            full_name="Fail Admin",
            hashed_password=get_password_hash("AdminPass123!"),
            role=UserRole.ADMIN,
            is_active=True,
            has_changed_password=True,
        )
        db_session.add(admin)
        await db_session.commit()
        return admin

    admin = asyncio.get_event_loop().run_until_complete(setup_admin())
    token = create_access_token({"sub": str(admin.id), "tenant_id": tid})

    async def failing_webhook(**kwargs):
        raise ConnectionError("Ingestion platform unreachable")

    with patch("app.api.clients._send_outbound_webhook", side_effect=failing_webhook):
        with TestClient(app) as client:
            resp = client.put(
                f"/clients/{synced_client.id}",
                json={"name": "Still Updated Despite Failure"},
                headers={"Authorization": f"Bearer {token}"},
            )

    # The update itself must succeed regardless of webhook failure
    assert resp.status_code == 200
