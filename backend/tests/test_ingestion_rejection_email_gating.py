"""
Regression tests for Fix 11 — the rejection email on an ingested timesheet
must be suppressed when the matching sender User is deactivated. Unknown
senders (no matching User row) still receive the reply, which is the normal
external-contractor flow.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

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


from app.api import ingestion as ingestion_api
from app.core.security import create_access_token, get_password_hash
from app.db import get_db
from app.models.base import Base
from app.models.ingested_email import IngestedEmail
from app.models.ingestion_timesheet import IngestionTimesheet, IngestionTimesheetStatus
from app.models.mailbox import Mailbox, MailboxAuthType, MailboxProtocol
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "ingestion_reject_email.db"
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
    app.include_router(ingestion_api.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _auth_headers(user: User) -> dict:
    token = create_access_token(
        {"sub": str(user.id), "tenant_id": user.tenant_id}
    )
    return {"Authorization": f"Bearer {token}"}


async def _scaffold(db_session: AsyncSession, *, sender_email: str) -> dict:
    tenant = Tenant(
        name="Tenant A", slug="tenant-a",
        status=TenantStatus.active, ingestion_enabled=True,
    )
    db_session.add(tenant)
    await db_session.flush()

    admin = User(
        tenant_id=tenant.id,
        email="admin@a.example",
        username="admin-a",
        full_name="Admin A",
        hashed_password=get_password_hash("password"),
        role=UserRole.ADMIN,
        is_active=True,
        email_verified=True,
        has_changed_password=True,
        can_review=True,
    )
    db_session.add(admin)
    await db_session.flush()

    mailbox = Mailbox(
        tenant_id=tenant.id,
        label="mbox",
        protocol=MailboxProtocol.imap,
        auth_type=MailboxAuthType.basic,
        is_active=True,
    )
    db_session.add(mailbox)
    await db_session.flush()

    email = IngestedEmail(
        tenant_id=tenant.id,
        mailbox_id=mailbox.id,
        message_id=f"<reject-{sender_email}>",
        sender_email=sender_email,
        subject="Timesheet",
        received_at=datetime.now(timezone.utc),
    )
    db_session.add(email)
    await db_session.flush()

    ts = IngestionTimesheet(
        tenant_id=tenant.id,
        email_id=email.id,
        status=IngestionTimesheetStatus.pending,
    )
    db_session.add(ts)
    await db_session.commit()

    return {"tenant": tenant, "admin": admin, "email": email, "timesheet": ts}


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejection_email_skipped_for_inactive_sender(db_session: AsyncSession):
    scaffold = await _scaffold(db_session, sender_email="offboarded@a.example")
    db_session.add(
        User(
            tenant_id=scaffold["tenant"].id,
            email="offboarded@a.example",
            username="offboarded-a",
            full_name="Ex Employee",
            hashed_password=get_password_hash("password"),
            role=UserRole.EMPLOYEE,
            is_active=False,
            email_verified=True,
            has_changed_password=True,
        )
    )
    await db_session.commit()

    sender = AsyncMock()
    client = _make_app(db_session)
    with client, patch("app.services.email_service.send_email", sender):
        response = client.post(
            f"/ingestion/timesheets/{scaffold['timesheet'].id}/reject",
            headers=_auth_headers(scaffold["admin"]),
            json={"reason": "hours do not reconcile"},
        )

    assert response.status_code == 200, response.text
    sender.assert_not_awaited()

    # Internal rejection record must still exist.
    await db_session.refresh(scaffold["timesheet"])
    assert scaffold["timesheet"].status == IngestionTimesheetStatus.rejected
    assert scaffold["timesheet"].rejection_reason == "hours do not reconcile"


@pytest.mark.asyncio
async def test_rejection_email_sent_for_active_sender(db_session: AsyncSession):
    scaffold = await _scaffold(db_session, sender_email="active@a.example")
    db_session.add(
        User(
            tenant_id=scaffold["tenant"].id,
            email="active@a.example",
            username="active-a",
            full_name="Active Employee",
            hashed_password=get_password_hash("password"),
            role=UserRole.EMPLOYEE,
            is_active=True,
            email_verified=True,
            has_changed_password=True,
        )
    )
    await db_session.commit()

    sender = AsyncMock()
    client = _make_app(db_session)
    with client, patch("app.services.email_service.send_email", sender):
        response = client.post(
            f"/ingestion/timesheets/{scaffold['timesheet'].id}/reject",
            headers=_auth_headers(scaffold["admin"]),
            json={"reason": "please resubmit with client split"},
        )

    assert response.status_code == 200, response.text
    sender.assert_awaited()

    await db_session.refresh(scaffold["timesheet"])
    assert scaffold["timesheet"].status == IngestionTimesheetStatus.rejected


@pytest.mark.asyncio
async def test_rejection_email_sent_for_unknown_sender(db_session: AsyncSession):
    """Sender doesn't match any User in the tenant — external contractor case."""
    scaffold = await _scaffold(db_session, sender_email="outsider@external.example")
    # No matching User row is created for this sender.

    sender = AsyncMock()
    client = _make_app(db_session)
    with client, patch("app.services.email_service.send_email", sender):
        response = client.post(
            f"/ingestion/timesheets/{scaffold['timesheet'].id}/reject",
            headers=_auth_headers(scaffold["admin"]),
            json={"reason": "missing billable flag"},
        )

    assert response.status_code == 200, response.text
    sender.assert_awaited()

    await db_session.refresh(scaffold["timesheet"])
    assert scaffold["timesheet"].status == IngestionTimesheetStatus.rejected
