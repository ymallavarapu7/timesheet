from datetime import date, timedelta
from decimal import Decimal

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import approvals, auth, clients, notifications, projects, tasks, timesheets, dashboard, time_off, time_off_approvals, users
from app.db import get_db
from app.core.deps import get_tenant_db
from app.core.security import get_password_hash
from app.models.base import Base
from app.models.client import Client
from app.models.project import Project
from app.models.tenant import Tenant, TenantStatus
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.time_off_request import TimeOffRequest, TimeOffStatus, TimeOffType
from app.models.user import User, UserRole
from app.models.assignments import EmployeeManagerAssignment


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "unit_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_data(db_session: AsyncSession) -> dict:
    tenant = Tenant(
        name="Test Tenant",
        slug="test-tenant",
        status=TenantStatus.active,
    )
    admin = User(
        tenant=tenant,
        email="admin@example.com",
        username="admin",
        full_name="Test Admin",
        hashed_password=get_password_hash("password"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    employee = User(
        tenant=tenant,
        email="emp@example.com",
        username="emp",
        full_name="Test Employee",
        title="Software Engineer",
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        is_active=True,
    )
    unassigned_employee = User(
        tenant=tenant,
        email="emp2@example.com",
        username="emp2",
        full_name="Unassigned Employee",
        title="QA Engineer",
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        is_active=True,
    )
    manager = User(
        tenant=tenant,
        email="manager@example.com",
        username="manager",
        full_name="Test Manager",
        hashed_password=get_password_hash("password"),
        role=UserRole.MANAGER,
        is_active=True,
    )
    senior_manager = User(
        tenant=tenant,
        email="senior.manager@example.com",
        username="senior-manager",
        full_name="Senior Manager",
        hashed_password=get_password_hash("password"),
        role=UserRole.MANAGER,
        is_active=True,
    )
    ceo = User(
        tenant=tenant,
        email="ceo@example.com",
        username="ceo",
        full_name="CEO Player",
        title="Chief Executive Officer",
        department="Executive",
        hashed_password=get_password_hash("password"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    inactive_employee = User(
        tenant=tenant,
        email="inactive.emp@example.com",
        username="inactive-emp",
        full_name="Inactive Employee",
        title="Contractor",
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        is_active=False,
    )
    client = Client(name="Test Client", tenant=tenant)

    db_session.add_all([tenant, admin, employee, unassigned_employee,
                       manager, senior_manager, ceo, inactive_employee, client])
    await db_session.flush()

    db_session.add(
        EmployeeManagerAssignment(
            employee_id=employee.id, manager_id=manager.id)
    )
    db_session.add(
        EmployeeManagerAssignment(
            employee_id=manager.id, manager_id=senior_manager.id)
    )

    project = Project(
        tenant=tenant,
        name="Unit Test Project",
        client_id=client.id,
        billable_rate=Decimal("150.00"),
        is_active=True,
    )
    second_project = Project(
        tenant=tenant,
        name="Restricted Project",
        client_id=client.id,
        billable_rate=Decimal("175.00"),
        is_active=True,
    )
    db_session.add_all([project, second_project])
    await db_session.flush()

    today = date.today()
    yesterday = today - timedelta(days=1)

    draft_entry = TimeEntry(
        tenant_id=tenant.id,
        user_id=employee.id,
        project_id=project.id,
        entry_date=today,
        hours=Decimal("8.00"),
        description="Draft entry",
        status=TimeEntryStatus.DRAFT,
    )
    submitted_entry = TimeEntry(
        tenant_id=tenant.id,
        user_id=employee.id,
        project_id=project.id,
        entry_date=yesterday,
        hours=Decimal("7.50"),
        description="Submitted entry",
        status=TimeEntryStatus.SUBMITTED,
    )

    time_off_draft = TimeOffRequest(
        tenant_id=tenant.id,
        user_id=employee.id,
        request_date=date(2026, 3, 13),
        hours=Decimal("4.00"),
        leave_type=TimeOffType.HALF_DAY,
        reason="Medical appointment",
        status=TimeOffStatus.DRAFT,
    )
    time_off_submitted = TimeOffRequest(
        tenant_id=tenant.id,
        user_id=employee.id,
        request_date=date(2026, 3, 10),
        hours=Decimal("8.00"),
        leave_type=TimeOffType.PTO,
        reason="Family event",
        status=TimeOffStatus.SUBMITTED,
    )

    db_session.add_all([draft_entry, submitted_entry,
                       time_off_draft, time_off_submitted])
    await db_session.commit()

    return {
        "tenant": tenant,
        "employee": employee,
        "unassigned_employee": unassigned_employee,
        "admin": admin,
        "manager": manager,
        "senior_manager": senior_manager,
        "ceo": ceo,
        "inactive_employee": inactive_employee,
        "client": client,
        "project": project,
        "second_project": second_project,
        "draft_entry": draft_entry,
        "submitted_entry": submitted_entry,
        "time_off_draft": time_off_draft,
        "time_off_submitted": time_off_submitted,
    }


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession, seeded_data: dict):
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(clients.router)
    app.include_router(projects.router)
    app.include_router(tasks.router)
    app.include_router(timesheets.router)
    app.include_router(approvals.router)
    app.include_router(time_off.router)
    app.include_router(time_off_approvals.router)
    app.include_router(dashboard.router)
    app.include_router(notifications.router)
    app.include_router(users.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_get_db
    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(api_client: TestClient) -> dict:
    login_response = api_client.post(
        "/auth/login",
        json={"email": "emp@example.com", "password": "password"},
    )
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def manager_auth_headers(api_client: TestClient) -> dict:
    login_response = api_client.post(
        "/auth/login",
        json={"email": "manager@example.com", "password": "password"},
    )
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def ceo_auth_headers(api_client: TestClient) -> dict:
    login_response = api_client.post(
        "/auth/login",
        json={"email": "ceo@example.com", "password": "password"},
    )
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def inactive_emp_auth_headers(api_client: TestClient) -> dict:
    login_response = api_client.post(
        "/auth/login",
        json={"email": "inactive.emp@example.com", "password": "password"},
    )
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_auth_headers(api_client: TestClient) -> dict:
    login_response = api_client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "password"},
    )
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def senior_manager_auth_headers(api_client: TestClient) -> dict:
    login_response = api_client.post(
        "/auth/login",
        json={"email": "senior.manager@example.com",
              "password": "password"},
    )
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
