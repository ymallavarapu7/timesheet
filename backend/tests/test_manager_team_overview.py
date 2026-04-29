"""Tests for ``GET /dashboard/manager-team-overview``.

Covers:
- 403 for EMPLOYEE / PLATFORM_ADMIN.
- 200 with empty team for a manager with no reports.
- Submitted-day counting against week-to-date entries.
- PTO classification: today, this week, next week, upcoming start.
- Repeatedly-late flag triggers when 2 of the last 3 working days were missed.
- Pending approvals + pending time-off + recent rejections aggregate correctly.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover
    return "JSON"


from app.api import dashboard as dashboard_api
from app.core.security import create_access_token, get_password_hash
from app.db import get_db
from app.core.deps import get_tenant_db
from app.models.assignments import EmployeeManagerAssignment
from app.models.base import Base
from app.models.client import Client
from app.models.project import Project
from app.models.tenant import Tenant, TenantStatus
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.time_off_request import TimeOffRequest, TimeOffStatus
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "manager_overview.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_app(db_session: AsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(dashboard_api.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_get_db
    return TestClient(app)


def _auth(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "tenant_id": user.tenant_id})
    return {"Authorization": f"Bearer {token}"}


async def _user(session, *, email, role, tenant_id, full_name=None) -> User:
    u = User(
        tenant_id=tenant_id,
        email=email,
        username=email.split("@")[0].replace(".", "-"),
        full_name=full_name or email,
        hashed_password=get_password_hash("password"),
        role=role,
        is_active=True,
        email_verified=True,
        has_changed_password=True,
    )
    session.add(u)
    await session.flush()
    return u


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


@pytest_asyncio.fixture
async def org(db_session: AsyncSession):
    tenant = Tenant(name="T", slug="t", status=TenantStatus.active)
    db_session.add(tenant)
    await db_session.flush()
    client = Client(name="C", tenant_id=tenant.id)
    db_session.add(client)
    await db_session.flush()
    project = Project(
        tenant_id=tenant.id, client_id=client.id, name="P",
        billable_rate=Decimal("100"), is_active=True,
    )
    db_session.add(project)
    manager = await _user(db_session, email="mgr@t.io", role=UserRole.MANAGER, tenant_id=tenant.id, full_name="Mgr One")
    await db_session.commit()
    return {"tenant": tenant, "project": project, "manager": manager}


async def _assign(session, *, manager: User, employee: User):
    session.add(EmployeeManagerAssignment(
        manager_id=manager.id,
        employee_id=employee.id,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Authorization
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_employee_gets_403(db_session, org):
    emp = await _user(db_session, email="emp@t.io", role=UserRole.EMPLOYEE, tenant_id=org["tenant"].id)
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(emp))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_platform_admin_gets_403(db_session):
    pa = await _user(db_session, email="pa@p.io", role=UserRole.PLATFORM_ADMIN, tenant_id=None)
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(pa))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_manager_with_no_reports_gets_empty(db_session, org):
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(org["manager"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["team_size"] == 0
    assert body["members"] == []
    assert body["pending_approvals_count"] == 0
    assert body["capacity_this_week"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Roster: submitted-day counts
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submitted_days_count_week_to_date(db_session, org):
    mgr = org["manager"]
    emp = await _user(db_session, email="alice@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="Alice")
    await _assign(db_session, manager=mgr, employee=emp)
    await db_session.commit()

    today = date.today()
    monday = _monday_of(today)
    # Two SUBMITTED entries this week, one APPROVED, both within week-to-date.
    for day_offset, status in [
        (0, TimeEntryStatus.SUBMITTED),
        (1, TimeEntryStatus.APPROVED),
    ]:
        d = monday + timedelta(days=day_offset)
        if d > today:
            continue
        db_session.add(TimeEntry(
            tenant_id=mgr.tenant_id,
            user_id=emp.id,
            project_id=org["project"].id,
            entry_date=d,
            hours=Decimal("8"),
            status=status,
            description="x",
        ))
    await db_session.commit()

    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(mgr))
    body = resp.json()
    assert body["team_size"] == 1
    member = body["members"][0]
    assert member["full_name"] == "Alice"
    # We expect both seeded days to count if they fell within today-or-earlier.
    expected = sum(1 for off in (0, 1) if monday + timedelta(days=off) <= today)
    assert member["submitted_days"] == expected


@pytest.mark.asyncio
async def test_draft_entries_do_not_count_as_submitted(db_session, org):
    mgr = org["manager"]
    emp = await _user(db_session, email="b@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="Bob")
    await _assign(db_session, manager=mgr, employee=emp)
    today = date.today()
    monday = _monday_of(today)
    db_session.add(TimeEntry(
        tenant_id=mgr.tenant_id, user_id=emp.id, project_id=org["project"].id,
        entry_date=monday, hours=Decimal("8"),
        status=TimeEntryStatus.DRAFT, description="x",
    ))
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(mgr))
    member = resp.json()["members"][0]
    assert member["submitted_days"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# PTO classification
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pto_today_and_this_week_flagged(db_session, org):
    mgr = org["manager"]
    emp = await _user(db_session, email="c@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="Carol")
    await _assign(db_session, manager=mgr, employee=emp)
    today = date.today()
    db_session.add(TimeOffRequest(
        tenant_id=mgr.tenant_id, user_id=emp.id, request_date=today,
        hours=Decimal("8"), leave_type="vacation", reason="vacay",
        status=TimeOffStatus.APPROVED,
    ))
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(mgr))
    body = resp.json()
    member = body["members"][0]
    assert member["is_on_pto_today"] is True
    assert member["is_on_pto_this_week"] is True
    assert len(body["capacity_this_week"]) == 1
    assert body["capacity_this_week"][0]["leave_type"] == "vacation"
    assert body["capacity_this_week"][0]["days_in_window"] == 1


@pytest.mark.asyncio
async def test_pto_next_week_separates_into_capacity_next_week(db_session, org):
    mgr = org["manager"]
    emp = await _user(db_session, email="d@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="Dan")
    await _assign(db_session, manager=mgr, employee=emp)
    today = date.today()
    monday = _monday_of(today)
    next_monday = monday + timedelta(days=7)
    db_session.add(TimeOffRequest(
        tenant_id=mgr.tenant_id, user_id=emp.id, request_date=next_monday,
        hours=Decimal("8"), leave_type="sick", reason="x",
        status=TimeOffStatus.SUBMITTED,
    ))
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(mgr))
    body = resp.json()
    assert body["capacity_this_week"] == []
    assert len(body["capacity_next_week"]) == 1
    member = body["members"][0]
    # Today is not the PTO date, so flag stays off; upcoming start is set.
    assert member["is_on_pto_today"] is False
    assert member["upcoming_pto_starts_at"] == next_monday.isoformat()


@pytest.mark.asyncio
async def test_draft_pto_does_not_consume_capacity(db_session, org):
    """DRAFT time-off requests don't claim capacity yet — they're not
    real commitments. Only SUBMITTED + APPROVED show up in the panel."""
    mgr = org["manager"]
    emp = await _user(db_session, email="e@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="Eve")
    await _assign(db_session, manager=mgr, employee=emp)
    today = date.today()
    db_session.add(TimeOffRequest(
        tenant_id=mgr.tenant_id, user_id=emp.id, request_date=today,
        hours=Decimal("8"), leave_type="personal", reason="x",
        status=TimeOffStatus.DRAFT,
    ))
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(mgr))
    body = resp.json()
    assert body["members"][0]["is_on_pto_today"] is False
    assert body["capacity_this_week"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Pattern: repeatedly late
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repeatedly_late_flag_triggers_when_two_of_three_missed(db_session, org):
    mgr = org["manager"]
    emp = await _user(db_session, email="f@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="Frank")
    await _assign(db_session, manager=mgr, employee=emp)
    # Backfill: only 1 of the last 3 weekdays has a submitted entry.
    # The endpoint computes the lookback at request time, so we don't
    # know exact dates — instead, leave only one SUBMITTED entry from
    # several days back. The endpoint will see "missed 2 of last 3".
    today = date.today()
    # Pick a weekday more than 4 days ago to ensure it falls outside
    # the lookback window. We add a SUBMITTED entry there to ensure
    # the user has *some* history but not in the lookback.
    far_back = today - timedelta(days=10)
    while far_back.weekday() >= 5:
        far_back -= timedelta(days=1)
    db_session.add(TimeEntry(
        tenant_id=mgr.tenant_id, user_id=emp.id, project_id=org["project"].id,
        entry_date=far_back, hours=Decimal("8"),
        status=TimeEntryStatus.SUBMITTED, description="x",
    ))
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(mgr))
    member = resp.json()["members"][0]
    assert member["is_repeatedly_late"] is True


@pytest.mark.asyncio
async def test_repeatedly_late_flag_clear_for_user_with_no_history(db_session, org):
    """A brand-new user (or freshly-onboarded employee) with zero
    submissions in the last 30 days should not be flagged as
    repeatedly-late — there's no signal yet, just an empty record."""
    mgr = org["manager"]
    emp = await _user(db_session, email="new@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="Brand New")
    await _assign(db_session, manager=mgr, employee=emp)
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(mgr))
    member = resp.json()["members"][0]
    assert member["is_repeatedly_late"] is False


@pytest.mark.asyncio
async def test_repeatedly_late_flag_clear_when_recent_submissions_present(db_session, org):
    mgr = org["manager"]
    emp = await _user(db_session, email="g@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="Gina")
    await _assign(db_session, manager=mgr, employee=emp)
    # Submit on each of the last 5 weekdays. Pattern flag should not trip.
    today = date.today()
    cursor = today - timedelta(days=1)
    added = 0
    while added < 5:
        if cursor.weekday() < 5:
            db_session.add(TimeEntry(
                tenant_id=mgr.tenant_id, user_id=emp.id, project_id=org["project"].id,
                entry_date=cursor, hours=Decimal("8"),
                status=TimeEntryStatus.SUBMITTED, description="x",
            ))
            added += 1
        cursor -= timedelta(days=1)
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(mgr))
    member = resp.json()["members"][0]
    assert member["is_repeatedly_late"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Priority counts
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_priority_counts_aggregate_correctly(db_session, org):
    mgr = org["manager"]
    emp = await _user(db_session, email="h@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="Hank")
    await _assign(db_session, manager=mgr, employee=emp)
    today = date.today()
    monday = _monday_of(today)
    # 2 pending approvals
    for off in (0, 1):
        d = monday + timedelta(days=off)
        if d > today:
            continue
        db_session.add(TimeEntry(
            tenant_id=mgr.tenant_id, user_id=emp.id, project_id=org["project"].id,
            entry_date=d, hours=Decimal("8"),
            status=TimeEntryStatus.SUBMITTED, description="x",
        ))
    # 1 rejected this week
    if monday <= today:
        db_session.add(TimeEntry(
            tenant_id=mgr.tenant_id, user_id=emp.id, project_id=org["project"].id,
            entry_date=monday, hours=Decimal("4"),
            status=TimeEntryStatus.REJECTED, description="x",
        ))
    # 1 pending time-off
    db_session.add(TimeOffRequest(
        tenant_id=mgr.tenant_id, user_id=emp.id, request_date=today + timedelta(days=14),
        hours=Decimal("8"), leave_type="vacation", reason="x",
        status=TimeOffStatus.SUBMITTED,
    ))
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(mgr))
    body = resp.json()
    # Pending approvals: at most 2 depending on what fits in week-to-date
    expected_approvals = sum(1 for off in (0, 1) if monday + timedelta(days=off) <= today)
    assert body["pending_approvals_count"] == expected_approvals
    expected_rejected = 1 if monday <= today else 0
    assert body["rejected_recent_count"] == expected_rejected
    assert body["pending_time_off_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Pending approval ages
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oldest_and_avg_pending_approval_age_compute(db_session, org):
    """submitted_at takes precedence; fall back to created_at when unset."""
    mgr = org["manager"]
    emp = await _user(db_session, email="age@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="Age")
    await _assign(db_session, manager=mgr, employee=emp)
    today = date.today()
    monday = _monday_of(today)
    now = datetime.now(timezone.utc)
    # 1 entry submitted ~30h ago, 1 submitted ~6h ago → oldest 30, avg 18.
    db_session.add(TimeEntry(
        tenant_id=mgr.tenant_id, user_id=emp.id, project_id=org["project"].id,
        entry_date=monday, hours=Decimal("8"),
        status=TimeEntryStatus.SUBMITTED, description="x",
        submitted_at=now - timedelta(hours=30),
    ))
    db_session.add(TimeEntry(
        tenant_id=mgr.tenant_id, user_id=emp.id, project_id=org["project"].id,
        entry_date=monday + timedelta(days=1), hours=Decimal("8"),
        status=TimeEntryStatus.SUBMITTED, description="x",
        submitted_at=now - timedelta(hours=6),
    ))
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(mgr))
    body = resp.json()
    assert body["pending_approvals_count"] == 2
    assert body["pending_approvals_oldest_hours"] in (29, 30)  # rounding tolerance
    assert body["pending_approvals_avg_hours"] in (17, 18)


@pytest.mark.asyncio
async def test_pending_approval_ages_null_when_queue_empty(db_session, org):
    mgr = org["manager"]
    emp = await _user(db_session, email="empty@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="Empty")
    await _assign(db_session, manager=mgr, employee=emp)
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-team-overview", headers=_auth(mgr))
    body = resp.json()
    assert body["pending_approvals_count"] == 0
    assert body["pending_approvals_oldest_hours"] is None
    assert body["pending_approvals_avg_hours"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Project health endpoint
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_project_health_403_for_employee(db_session, org):
    emp = await _user(db_session, email="emp@p.io", role=UserRole.EMPLOYEE, tenant_id=org["tenant"].id)
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-project-health", headers=_auth(emp))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_project_health_empty_when_no_team(db_session, org):
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-project-health", headers=_auth(org["manager"]))
    assert resp.status_code == 200
    assert resp.json() == {"rows": []}


@pytest.mark.asyncio
async def test_project_health_includes_only_projects_with_recent_entries(db_session, org):
    mgr = org["manager"]
    emp = await _user(db_session, email="ph@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="PH")
    await _assign(db_session, manager=mgr, employee=emp)
    # Add a second project the team has *not* logged to. Should not appear.
    other = Project(
        tenant_id=mgr.tenant_id, client_id=org["project"].client_id, name="Other",
        billable_rate=Decimal("100"), is_active=True,
    )
    db_session.add(other)
    await db_session.flush()
    today = date.today()
    monday = _monday_of(today)
    db_session.add(TimeEntry(
        tenant_id=mgr.tenant_id, user_id=emp.id, project_id=org["project"].id,
        entry_date=monday, hours=Decimal("8"),
        status=TimeEntryStatus.SUBMITTED, description="x",
    ))
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-project-health", headers=_auth(mgr))
    body = resp.json()
    project_names = [r["project_name"] for r in body["rows"]]
    assert "P" in project_names
    assert "Other" not in project_names


@pytest.mark.asyncio
async def test_project_health_classifies_over_budget_as_needs_attention(db_session, org):
    mgr = org["manager"]
    emp = await _user(db_session, email="ob@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="OB")
    await _assign(db_session, manager=mgr, employee=emp)
    # Set the project's estimated_hours to 10; log 12.
    org["project"].estimated_hours = Decimal("10")
    db_session.add(org["project"])
    today = date.today()
    monday = _monday_of(today)
    db_session.add(TimeEntry(
        tenant_id=mgr.tenant_id, user_id=emp.id, project_id=org["project"].id,
        entry_date=monday, hours=Decimal("12"),
        status=TimeEntryStatus.APPROVED, description="x",
    ))
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-project-health", headers=_auth(mgr))
    row = resp.json()["rows"][0]
    assert row["health"] == "needs-attention"
    assert row["budget_pct"] == 120


@pytest.mark.asyncio
async def test_project_health_not_set_when_no_budget_and_no_end_date(db_session, org):
    mgr = org["manager"]
    emp = await _user(db_session, email="ns@t.io", role=UserRole.EMPLOYEE, tenant_id=mgr.tenant_id, full_name="NS")
    await _assign(db_session, manager=mgr, employee=emp)
    today = date.today()
    monday = _monday_of(today)
    db_session.add(TimeEntry(
        tenant_id=mgr.tenant_id, user_id=emp.id, project_id=org["project"].id,
        entry_date=monday, hours=Decimal("3"),
        status=TimeEntryStatus.SUBMITTED, description="x",
    ))
    await db_session.commit()
    with _make_app(db_session) as client:
        resp = client.get("/dashboard/manager-project-health", headers=_auth(mgr))
    row = resp.json()["rows"][0]
    assert row["health"] == "not-set"
    assert row["budget_pct"] is None
    assert row["days_until_end"] is None
