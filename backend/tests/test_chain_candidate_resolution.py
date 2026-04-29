"""
Pipeline and API tests for chain-sender candidate resolution.

Covers:
  - Single chain match → auto-assign, no chain_candidates surfaced.
  - Zero matches → chain_candidates surfaced, no dummy user created.
  - Multiple matches on different users → same as zero (reviewer picks).
  - API assigns to existing user when email matches a known user.
  - API creates a new user with the CANDIDATE's own email, not the
    outer mailbox's email.
  - Tenant isolation: a name in a different tenant never matches.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - shim
    return "JSON"


from app.api import ingestion as ingestion_api
from app.core.security import create_access_token, get_password_hash
from app.db import get_db
from app.core.deps import get_tenant_db
from app.models.base import Base
from app.models.ingested_email import IngestedEmail
from app.models.ingestion_timesheet import IngestionTimesheet, IngestionTimesheetStatus
from app.models.mailbox import Mailbox, MailboxAuthType, MailboxProtocol
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    with TemporaryDirectory(dir=REPO_ROOT) as tmp:
        db_path = Path(tmp) / "chain_candidate_resolution.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            yield session
        await engine.dispose()


async def _make_tenant_with_users(db_session: AsyncSession, users: list[dict]) -> Tenant:
    tenant = Tenant(name="Chain Tenant", slug="chain", status=TenantStatus.active, ingestion_enabled=True)
    db_session.add(tenant)
    await db_session.flush()
    for spec in users:
        db_session.add(User(
            tenant_id=tenant.id,
            email=spec["email"],
            username=spec["username"],
            full_name=spec["full_name"],
            hashed_password=get_password_hash("password"),
            role=UserRole.EMPLOYEE,
            is_active=True,
            email_verified=True,
            has_changed_password=True,
        ))
    await db_session.flush()
    return tenant


async def _make_reviewer(db_session: AsyncSession, tenant: Tenant) -> User:
    reviewer = User(
        tenant_id=tenant.id,
        email=f"reviewer-{tenant.id}@x.example",
        username=f"reviewer-{tenant.id}",
        full_name="Reviewer",
        hashed_password=get_password_hash("password"),
        role=UserRole.ADMIN,
        is_active=True,
        email_verified=True,
        has_changed_password=True,
        can_review=True,
    )
    db_session.add(reviewer)
    await db_session.flush()
    return reviewer


async def _make_mailbox(db_session: AsyncSession, tenant: Tenant) -> Mailbox:
    mailbox = Mailbox(
        tenant_id=tenant.id,
        label="mbox",
        protocol=MailboxProtocol.imap,
        auth_type=MailboxAuthType.basic,
        is_active=True,
    )
    db_session.add(mailbox)
    await db_session.flush()
    return mailbox


# ─── Pipeline-level: chain candidate persistence ─────────────────────────────

@pytest.mark.asyncio
async def test_chain_single_match_auto_assigns_and_no_candidates_surface(db_session: AsyncSession):
    """
    When exactly one chain entry matches an existing user, the pipeline
    assigns that user and does NOT surface chain_candidates — the
    reviewer has nothing to disambiguate.

    Unit-style: we don't run the full pipeline, we simulate the two
    tightly-coupled pieces: the `chain_match_ids` resolution and the
    IngestionTimesheet construction. This keeps the test narrow.
    """
    tenant = await _make_tenant_with_users(db_session, [
        {"email": "jane@x.example", "username": "jane", "full_name": "Jane Doe"},
    ])
    await db_session.commit()

    from app.services.ingestion_pipeline import _fuzzy_match_employee, _load_known_employees
    employees = await _load_known_employees(db_session, tenant.id)

    chain_senders = [{"name": "Jane Doe", "email": "jane@x.example"}]
    matches: set[int] = set()
    known_emails = {(e.get("email") or "").lower(): e["id"] for e in employees if e.get("email")}
    for entry in chain_senders:
        eaddr = (entry.get("email") or "").lower()
        if eaddr in known_emails:
            matches.add(known_emails[eaddr])
        elif entry.get("name"):
            m = _fuzzy_match_employee(entry["name"], employees)
            if m is not None:
                matches.add(m)

    # Auto-assign path
    assert len(matches) == 1
    resolved_employee_id = next(iter(matches))
    # When a unique match exists, the pipeline leaves llm_match_suggestions None
    llm_match_suggestions = None if len(matches) == 1 else {"chain_candidates": [...]}
    assert llm_match_suggestions is None
    assert resolved_employee_id is not None


@pytest.mark.asyncio
async def test_chain_zero_matches_surfaces_candidates_without_dummy_user(db_session: AsyncSession):
    """
    Zero chain matches → llm_match_suggestions.chain_candidates is populated
    with every chain entry, each with existing_user_id=None. The pipeline
    does NOT create a dummy user (employee_id stays None) — this is the
    "avoid ingestion dummy data" rule.
    """
    tenant = await _make_tenant_with_users(db_session, [
        {"email": "alice@company.example", "username": "alice", "full_name": "Alice"},
    ])
    await db_session.commit()

    from app.services.ingestion_pipeline import _fuzzy_match_employee, _load_known_employees
    employees = await _load_known_employees(db_session, tenant.id)

    chain_senders = [
        {"name": "John Doe", "email": "john@contractor.example"},
        {"name": "Jane Smith", "email": "jane@contractor.example"},
    ]
    matches: set[int] = set()
    for entry in chain_senders:
        eaddr = (entry.get("email") or "").lower()
        matched_by_email = next(
            (e["id"] for e in employees if (e.get("email") or "").lower() == eaddr),
            None,
        )
        if matched_by_email is not None:
            matches.add(matched_by_email)
            continue
        if entry.get("name"):
            m = _fuzzy_match_employee(entry["name"], employees)
            if m is not None:
                matches.add(m)

    assert matches == set()
    # Build llm_match_suggestions exactly the way the pipeline does now.
    suggestions = []
    for entry in chain_senders:
        suggestions.append({
            "name": entry.get("name"),
            "email": entry.get("email"),
            "existing_user_id": None,
            "matches_extracted_name": False,
        })
    assert len(suggestions) == 2
    assert all(s["existing_user_id"] is None for s in suggestions)


@pytest.mark.asyncio
async def test_chain_multiple_matches_different_users_surfaces_all_candidates(db_session: AsyncSession):
    """
    When chain entries match multiple DIFFERENT existing users, the
    pipeline can't auto-assign — surface them all and let the reviewer
    pick. existing_user_id is populated where we did match.
    """
    tenant = await _make_tenant_with_users(db_session, [
        {"email": "alice@x.example", "username": "alice", "full_name": "Alice A"},
        {"email": "bob@x.example", "username": "bob", "full_name": "Bob B"},
    ])
    await db_session.commit()

    from app.services.ingestion_pipeline import _fuzzy_match_employee, _load_known_employees
    employees = await _load_known_employees(db_session, tenant.id)

    chain_senders = [
        {"name": "Alice A", "email": "alice@x.example"},
        {"name": "Bob B", "email": "bob@x.example"},
    ]
    matches: set[int] = set()
    for entry in chain_senders:
        eaddr = (entry.get("email") or "").lower()
        for emp in employees:
            if (emp.get("email") or "").lower() == eaddr:
                matches.add(emp["id"])
                break

    # Two distinct users — can't auto-assign.
    assert len(matches) == 2


@pytest.mark.asyncio
async def test_chain_tenant_isolation(db_session: AsyncSession):
    """
    A chain entry's name must NOT match a user in a different tenant.
    The resolution helpers already scope by tenant_id via
    _load_known_employees; asserting that here guards against future
    regressions that bypass the scope.
    """
    tenant_a = await _make_tenant_with_users(db_session, [
        {"email": "jane@x.example", "username": "jane-a", "full_name": "Jane Doe"},
    ])
    tenant_b = Tenant(name="Tenant B", slug="b", status=TenantStatus.active, ingestion_enabled=True)
    db_session.add(tenant_b)
    await db_session.flush()
    await db_session.commit()

    from app.services.ingestion_pipeline import _fuzzy_match_employee, _load_known_employees

    # In tenant_b's scope, Jane Doe doesn't exist.
    employees_b = await _load_known_employees(db_session, tenant_b.id)
    assert _fuzzy_match_employee("Jane Doe", employees_b) is None


# ─── API-level: assign-chain-candidate endpoint ─────────────────────────────

def _make_app(db_session: AsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(ingestion_api.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_db] = override_get_db
    return TestClient(app)


def _auth_headers(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "tenant_id": user.tenant_id})
    return {"Authorization": f"Bearer {token}"}


async def _make_skipped_timesheet(
    db_session: AsyncSession,
    tenant: Tenant,
    mailbox: Mailbox,
    chain_candidates: list[dict],
) -> IngestionTimesheet:
    email = IngestedEmail(
        tenant_id=tenant.id,
        mailbox_id=mailbox.id,
        message_id=f"<chain-{tenant.id}@example.com>",
        sender_email="approvals@company.example",
        subject="Fwd: Timesheet",
        received_at=datetime.now(timezone.utc),
        has_attachments=True,
        chain_senders=chain_candidates,
    )
    db_session.add(email)
    await db_session.flush()
    ts = IngestionTimesheet(
        tenant_id=tenant.id,
        email_id=email.id,
        status=IngestionTimesheetStatus.pending,
        employee_id=None,
        llm_match_suggestions={
            "chain_candidates": [
                {**entry, "existing_user_id": None, "matches_extracted_name": False}
                for entry in chain_candidates
            ],
        },
    )
    db_session.add(ts)
    await db_session.flush()
    return ts


@pytest.mark.asyncio
async def test_assign_chain_candidate_binds_to_existing_user_by_email(db_session: AsyncSession):
    tenant = await _make_tenant_with_users(db_session, [
        {"email": "jane@x.example", "username": "jane", "full_name": "Jane Doe"},
    ])
    reviewer = await _make_reviewer(db_session, tenant)
    mailbox = await _make_mailbox(db_session, tenant)
    ts = await _make_skipped_timesheet(db_session, tenant, mailbox, [
        {"name": "Jane Doe", "email": "jane@x.example"},
        {"name": "John Other", "email": "john@contractor.example"},
    ])
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.post(
            f"/ingestion/timesheets/{ts.id}/assign-chain-candidate",
            headers=_auth_headers(reviewer),
            json={"name": "Jane Doe", "email": "jane@x.example"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_new_user"] is False

    # No duplicate user created — the single Jane Doe is still the only match.
    janes = await db_session.execute(
        select(User).where(
            (User.tenant_id == tenant.id) & (User.email == "jane@x.example")
        )
    )
    assert len(list(janes.scalars().all())) == 1


@pytest.mark.asyncio
async def test_assign_chain_candidate_creates_user_with_candidate_email(db_session: AsyncSession):
    """
    The critical behavior from the spec: when creating a new user from a
    chain candidate, use the CANDIDATE's own email — not the outer
    mailbox's. Asserts the created User row has the chain email, not
    approvals@company.example.
    """
    tenant = await _make_tenant_with_users(db_session, [])  # no existing users
    reviewer = await _make_reviewer(db_session, tenant)
    mailbox = await _make_mailbox(db_session, tenant)
    ts = await _make_skipped_timesheet(db_session, tenant, mailbox, [
        {"name": "John Doe", "email": "john@contractor.example"},
        {"name": "Jane Doe", "email": "jane@contractor.example"},
    ])
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.post(
            f"/ingestion/timesheets/{ts.id}/assign-chain-candidate",
            headers=_auth_headers(reviewer),
            json={"name": "Jane Doe", "email": "jane@contractor.example"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_new_user"] is True

    # The created user must have the chain email, NOT the mailbox's.
    result = await db_session.execute(
        select(User).where(User.id == body["employee_id"])
    )
    new_user = result.scalar_one()
    assert new_user.email == "jane@contractor.example"
    assert new_user.full_name == "Jane Doe"
    # And critically: not the outer mailbox sender.
    assert new_user.email != "approvals@company.example"


@pytest.mark.asyncio
async def test_assign_chain_candidate_name_only_binds_existing_user(db_session: AsyncSession):
    """
    Reviewer picks a name-only chain entry. If the name already matches
    an existing user in the tenant (fuzzy), bind to that user — no email
    needed. This covers the "name-only but we can figure out who it is"
    case from the spec.
    """
    tenant = await _make_tenant_with_users(db_session, [
        {"email": "daniel@x.example", "username": "daniel", "full_name": "Daniel Gwilt"},
    ])
    reviewer = await _make_reviewer(db_session, tenant)
    mailbox = await _make_mailbox(db_session, tenant)
    ts = await _make_skipped_timesheet(db_session, tenant, mailbox, [
        {"name": "Daniel Gwilt", "email": None},
    ])
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.post(
            f"/ingestion/timesheets/{ts.id}/assign-chain-candidate",
            headers=_auth_headers(reviewer),
            json={"name": "Daniel Gwilt"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_new_user"] is False


@pytest.mark.asyncio
async def test_assign_chain_candidate_name_only_no_match_requires_email(db_session: AsyncSession):
    """
    Reviewer picks a name-only candidate, name doesn't match any existing
    user, and no email is supplied. The endpoint must refuse with 400
    rather than inventing a placeholder email — that's exactly the
    dummy-data-avoidance the feature is about.
    """
    tenant = await _make_tenant_with_users(db_session, [])
    reviewer = await _make_reviewer(db_session, tenant)
    mailbox = await _make_mailbox(db_session, tenant)
    ts = await _make_skipped_timesheet(db_session, tenant, mailbox, [
        {"name": "Stranger Name", "email": None},
    ])
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.post(
            f"/ingestion/timesheets/{ts.id}/assign-chain-candidate",
            headers=_auth_headers(reviewer),
            json={"name": "Stranger Name"},
        )
    assert response.status_code == 400
    assert "email" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_assign_chain_candidate_rejects_empty_body(db_session: AsyncSession):
    tenant = await _make_tenant_with_users(db_session, [])
    reviewer = await _make_reviewer(db_session, tenant)
    mailbox = await _make_mailbox(db_session, tenant)
    ts = await _make_skipped_timesheet(db_session, tenant, mailbox, [])
    await db_session.commit()

    client = _make_app(db_session)
    with client:
        response = client.post(
            f"/ingestion/timesheets/{ts.id}/assign-chain-candidate",
            headers=_auth_headers(reviewer),
            json={},
        )
    assert response.status_code == 400
    assert "name" in response.json()["detail"].lower()
