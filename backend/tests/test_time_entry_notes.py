"""
Tests for the new private ``notes`` field on TimeEntry.

The field is additive and optional. Create should accept it, update should
accept it, and the GET endpoint should round-trip it. Existing entries with
NULL notes must continue to work — no regressions to Batch 1/2/3 behavior.
"""
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - test shim
    return "JSON"


from app.api import timesheets as timesheets_api
from app.core.security import create_access_token, get_password_hash
from app.db import get_db
from app.core.deps import get_tenant_db
from app.models.base import Base
from app.models.client import Client
from app.models.project import Project
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "notes_field.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


def _make_app(db_session: AsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(timesheets_api.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_get_db
    return TestClient(app)


def _auth_headers(user: User) -> dict:
    token = create_access_token(
        {"sub": str(user.id), "tenant_id": user.tenant_id}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def seed(db_session: AsyncSession) -> dict:
    tenant = Tenant(name="Tenant A", slug="tenant-a", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.flush()

    client = Client(name="Client A", tenant_id=tenant.id)
    db_session.add(client)
    await db_session.flush()

    project = Project(
        tenant_id=tenant.id,
        client_id=client.id,
        name="Project A",
        billable_rate=Decimal("100.00"),
        is_active=True,
    )
    db_session.add(project)
    await db_session.flush()

    emp = User(
        tenant_id=tenant.id,
        email="emp@a.example",
        username="emp-a",
        full_name="Employee A",
        title="Engineer",
        hashed_password=get_password_hash("password"),
        role=UserRole.EMPLOYEE,
        is_active=True,
        email_verified=True,
        has_changed_password=True,
    )
    db_session.add(emp)
    await db_session.commit()

    return {"tenant": tenant, "project": project, "emp": emp}


def _create_payload(project_id: int, **extra) -> dict:
    base = {
        "project_id": project_id,
        "entry_date": date.today().isoformat(),
        "hours": "8.00",
        "description": "Worked on project",
    }
    base.update(extra)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Create round-trips notes
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_persists_notes(db_session: AsyncSession, seed: dict):
    client = _make_app(db_session)
    with client:
        response = client.post(
            "/timesheets",
            headers=_auth_headers(seed["emp"]),
            json=_create_payload(
                seed["project"].id, notes="blocked on api key from ops"
            ),
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["notes"] == "blocked on api key from ops"


@pytest.mark.asyncio
async def test_create_without_notes_defaults_to_none(
    db_session: AsyncSession, seed: dict
):
    """Back-compat: existing clients that don't send notes must still succeed,
    and the response must return ``notes: None`` rather than 422/500."""
    client = _make_app(db_session)
    with client:
        response = client.post(
            "/timesheets",
            headers=_auth_headers(seed["emp"]),
            json=_create_payload(seed["project"].id),
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body.get("notes") is None


# ─────────────────────────────────────────────────────────────────────────────
# Update round-trips notes
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_sets_notes(db_session: AsyncSession, seed: dict):
    client = _make_app(db_session)
    with client:
        create_resp = client.post(
            "/timesheets",
            headers=_auth_headers(seed["emp"]),
            json=_create_payload(seed["project"].id),
        )
        assert create_resp.status_code == 201, create_resp.text
        entry_id = create_resp.json()["id"]

        update_resp = client.put(
            f"/timesheets/{entry_id}",
            headers=_auth_headers(seed["emp"]),
            json={
                "notes": "added a reminder to follow up with Sarah",
                "edit_reason": "add private context",
                "history_summary": "Added notes",
            },
        )

    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["notes"] == "added a reminder to follow up with Sarah"


@pytest.mark.asyncio
async def test_update_can_clear_notes(db_session: AsyncSession, seed: dict):
    client = _make_app(db_session)
    with client:
        create_resp = client.post(
            "/timesheets",
            headers=_auth_headers(seed["emp"]),
            json=_create_payload(seed["project"].id, notes="scratch"),
        )
        entry_id = create_resp.json()["id"]

        update_resp = client.put(
            f"/timesheets/{entry_id}",
            headers=_auth_headers(seed["emp"]),
            json={
                "notes": None,
                "edit_reason": "clear private notes",
                "history_summary": "Removed notes",
            },
        )

    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json().get("notes") is None


# ─────────────────────────────────────────────────────────────────────────────
# Notes do not affect description and vice versa
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notes_and_description_are_independent(
    db_session: AsyncSession, seed: dict
):
    """Notes should not be merged into description, nor leak across fields."""
    client = _make_app(db_session)
    with client:
        resp = client.post(
            "/timesheets",
            headers=_auth_headers(seed["emp"]),
            json=_create_payload(
                seed["project"].id,
                description="Implemented login flow",
                notes="deploy blocked until staging reset",
            ),
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["description"] == "Implemented login flow"
    assert body["notes"] == "deploy blocked until staging reset"
    assert "deploy blocked" not in body["description"]
    assert "Implemented login flow" not in (body["notes"] or "")
