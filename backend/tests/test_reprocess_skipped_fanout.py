"""
Regression tests for the reprocess-skipped fan-out and the pdftoppm timeout.

Context: the previous reprocess-skipped path ran every skipped email in a
single arq job's main loop. One slow attachment (typically a hung pdftoppm
subprocess or a long Vision extraction) would consume the entire 300s
job_timeout and kill the batch mid-flight, leaving the rest of the list
stuck. Two fixes landed together:

  A. pdftoppm call is wrapped in asyncio.wait_for(..., timeout=60) so one
     malformed PDF can't hang the extraction path — same pattern used for
     antiword on the .doc path.
  B. The /fetch-emails/reprocess-skipped API endpoint now queries skipped
     email ids server-side and fans out one reprocess_email arq job per
     email id. Arq's worker pool runs them concurrently and each has its
     own 300s budget, so one slow email can't poison the rest.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
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
        db_path = Path(tmp) / "reprocess_fanout.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            yield session
        await engine.dispose()


async def _scaffold_tenant_with_skipped(db_session: AsyncSession, skipped_count: int) -> dict:
    tenant = Tenant(name="Fanout Tenant", slug="fanout", status=TenantStatus.active, ingestion_enabled=True)
    db_session.add(tenant)
    await db_session.flush()

    reviewer = User(
        tenant_id=tenant.id,
        email="reviewer@fanout.example",
        username="fanout-reviewer",
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

    mailbox = Mailbox(
        tenant_id=tenant.id,
        label="mbox",
        protocol=MailboxProtocol.imap,
        auth_type=MailboxAuthType.basic,
        is_active=True,
    )
    db_session.add(mailbox)
    await db_session.flush()

    skipped_ids: list[int] = []
    for i in range(skipped_count):
        email = IngestedEmail(
            tenant_id=tenant.id,
            mailbox_id=mailbox.id,
            message_id=f"<skipped-{i}@test>",
            sender_email=f"sender{i}@test.example",
            subject=f"Timesheet {i}",
            received_at=datetime(2026, 4, 20 + i % 5, tzinfo=timezone.utc),
            has_attachments=True,
        )
        db_session.add(email)
        await db_session.flush()
        skipped_ids.append(email.id)

    # One non-skipped email (has a timesheet row) — must NOT end up in the fan-out.
    not_skipped = IngestedEmail(
        tenant_id=tenant.id,
        mailbox_id=mailbox.id,
        message_id="<processed@test>",
        sender_email="already@test.example",
        subject="Already processed",
        received_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
        has_attachments=True,
    )
    db_session.add(not_skipped)
    await db_session.flush()
    db_session.add(
        IngestionTimesheet(
            tenant_id=tenant.id,
            email_id=not_skipped.id,
            status=IngestionTimesheetStatus.pending,
        )
    )
    await db_session.commit()

    return {"tenant": tenant, "reviewer": reviewer, "skipped_ids": skipped_ids}


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


@pytest.mark.asyncio
async def test_reprocess_skipped_endpoint_fans_out_per_email(db_session: AsyncSession):
    """
    POST /ingestion/fetch-emails/reprocess-skipped now queries the set of
    skipped email ids server-side and fans out one arq job per email,
    rather than enqueueing a single batch job that walks the list serially.
    Assert the API calls the fan-out helper with exactly the skipped ids
    (and only those — emails that already have IngestionTimesheet rows
    must be excluded).
    """
    scaffold = await _scaffold_tenant_with_skipped(db_session, skipped_count=3)
    expected_ids = scaffold["skipped_ids"]

    fanout_mock = AsyncMock(return_value="reprocess_skipped_batch_tenant_1_123")
    client = _make_app(db_session)
    with client, patch(
        "app.api.ingestion.enqueue_reprocess_skipped_fanout", fanout_mock
    ):
        response = client.post(
            "/ingestion/fetch-emails/reprocess-skipped",
            headers=_auth_headers(scaffold["reviewer"]),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"].startswith("reprocess_skipped_batch_tenant_")

    # Fan-out must have been called exactly once, with the tenant id and
    # the list of skipped email ids (order doesn't matter for correctness).
    fanout_mock.assert_awaited_once()
    call_args = fanout_mock.await_args
    assert call_args.args[0] == scaffold["tenant"].id
    assert set(call_args.args[1]) == set(expected_ids)


@pytest.mark.asyncio
async def test_reprocess_skipped_endpoint_no_emails_still_dispatches_cleanly(
    db_session: AsyncSession,
):
    """
    An empty skipped list should still return a valid response — the
    fan-out helper handles the empty case by writing a `complete` status
    immediately. The API must not raise.
    """
    scaffold = await _scaffold_tenant_with_skipped(db_session, skipped_count=0)

    fanout_mock = AsyncMock(return_value="reprocess_skipped_batch_tenant_1_empty")
    client = _make_app(db_session)
    with client, patch(
        "app.api.ingestion.enqueue_reprocess_skipped_fanout", fanout_mock
    ):
        response = client.post(
            "/ingestion/fetch-emails/reprocess-skipped",
            headers=_auth_headers(scaffold["reviewer"]),
        )

    assert response.status_code == 200, response.text
    fanout_mock.assert_awaited_once()
    assert list(fanout_mock.await_args.args[1]) == []


@pytest.mark.asyncio
async def test_rasterize_pdf_timeout_falls_back_to_pdf2image():
    """
    The pdftoppm subprocess is now wrapped in asyncio.wait_for(timeout=60).
    Simulate a hanging pdftoppm by returning a fake process whose
    communicate() never resolves, and assert _rasterize_pdf doesn't hang
    forever — it must raise (and then the extractor's own try/except falls
    back to pdf2image).

    We use a tiny timeout override via monkeypatching asyncio.wait_for so
    the test doesn't actually sleep 60s; the important assertion is that
    TimeoutError → proc.kill → RuntimeError("pdftoppm timed out") path
    runs cleanly.
    """
    from app.services import extraction

    class _FakeProc:
        def __init__(self):
            self.returncode = None
            self._killed = False

        async def communicate(self):
            # Never resolves — simulate a hung pdftoppm.
            await asyncio.Event().wait()

        def kill(self):
            self._killed = True
            self.returncode = -9

        async def wait(self):
            return self.returncode

    fake_proc = _FakeProc()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return fake_proc

    # Patch wait_for to a 0.1s budget so the test completes in <1s instead
    # of waiting for the real 60s timeout. The behaviour under test is the
    # TimeoutError → kill → fallback path, not the literal 60s duration.
    real_wait_for = asyncio.wait_for

    async def fast_wait_for(coro, timeout):
        return await real_wait_for(coro, timeout=min(timeout, 0.1))

    # Stub the pdf2image fallback so we don't need a real PDF — returning
    # an empty list short-circuits the fallback and lets the function
    # complete.
    class _FakePdf2ImageModule:
        @staticmethod
        def convert_from_bytes(*args, **kwargs):
            return []

    with patch.object(asyncio, "create_subprocess_exec", fake_create_subprocess_exec), \
         patch.object(asyncio, "wait_for", fast_wait_for), \
         patch.dict(
             "sys.modules",
             {"pdf2image": _FakePdf2ImageModule()},
         ):
        pages = await extraction._rasterize_pdf(b"%PDF-1.4 fake content")

    # Fallback ran (pages is the empty list from the stub) and the hung
    # subprocess was killed — no hang, no unhandled exception.
    assert pages == []
    assert fake_proc._killed is True
