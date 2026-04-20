"""
Regression tests for the ingestion attachment endpoints.

Verifies that:
  * The attachment tenant check is enforced in SQL (joins IngestedEmail and
    filters on tenant_id), not via a lazy-loaded relationship attribute.
  * Cross-tenant access returns 404 and never leaks attachment metadata.
  * Orphaned attachments (no matching ingested_email row) return 404 without
    raising AttributeError.
"""
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

# JSONB → JSON shim for SQLite table creation (test-only).
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - test shim
    return "JSON"


from app.api import ingestion
from app.core.security import create_access_token, get_password_hash
from app.db import get_db
from app.models.base import Base
from app.models.email_attachment import EmailAttachment, ExtractionStatus
from app.models.ingested_email import IngestedEmail
from app.models.mailbox import Mailbox, MailboxAuthType, MailboxProtocol
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "ingestion_tenant.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def two_tenants_with_attachment(db_session: AsyncSession) -> dict:
    """Tenant A owns an IngestedEmail with an EmailAttachment; Tenant B has an admin."""
    tenant_a = Tenant(
        name="Tenant A",
        slug="tenant-a",
        status=TenantStatus.active,
        ingestion_enabled=True,
    )
    tenant_b = Tenant(
        name="Tenant B",
        slug="tenant-b",
        status=TenantStatus.active,
        ingestion_enabled=True,
    )
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()

    admin_a = User(
        tenant_id=tenant_a.id,
        email="admin@a.example",
        username="admin-a",
        full_name="Admin A",
        hashed_password=get_password_hash("password"),
        role=UserRole.ADMIN,
        is_active=True,
        has_changed_password=True,
        email_verified=True,
        can_review=True,
    )
    admin_b = User(
        tenant_id=tenant_b.id,
        email="admin@b.example",
        username="admin-b",
        full_name="Admin B",
        hashed_password=get_password_hash("password"),
        role=UserRole.ADMIN,
        is_active=True,
        has_changed_password=True,
        email_verified=True,
        can_review=True,
    )
    db_session.add_all([admin_a, admin_b])
    await db_session.flush()

    mailbox_a = Mailbox(
        tenant_id=tenant_a.id,
        label="Tenant A mailbox",
        protocol=MailboxProtocol.imap,
        auth_type=MailboxAuthType.basic,
        is_active=True,
    )
    db_session.add(mailbox_a)
    await db_session.flush()

    email = IngestedEmail(
        tenant_id=tenant_a.id,
        mailbox_id=mailbox_a.id,
        message_id="<attach-1@a.example>",
        sender_email="sender@a.example",
    )
    db_session.add(email)
    await db_session.flush()

    attachment = EmailAttachment(
        email_id=email.id,
        filename="secret-tenant-a.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=100,
        storage_key="tenant-a/attach/1.xlsx",
        extraction_status=ExtractionStatus.completed,
    )
    db_session.add(attachment)
    await db_session.commit()

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "admin_a": admin_a,
        "admin_b": admin_b,
        "email": email,
        "attachment": attachment,
    }


def _make_app(db_session: AsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(ingestion.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _auth_headers(user: User) -> dict:
    """Mint an access token directly; avoids slowapi rate-limiting on /auth/login."""
    token = create_access_token(
        {"sub": str(user.id), "tenant_id": user.tenant_id}
    )
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_attachment_file_cross_tenant_returns_404(
    db_session: AsyncSession, two_tenants_with_attachment: dict
):
    attachment_id = two_tenants_with_attachment["attachment"].id
    admin_b = two_tenants_with_attachment["admin_b"]

    client = _make_app(db_session)
    with client, patch(
        "app.api.ingestion.read_file", new=AsyncMock(return_value=b"secret")
    ):
        response = client.get(
            f"/ingestion/attachments/{attachment_id}/file",
            headers=_auth_headers(admin_b),
        )

    assert response.status_code == 404
    # Must not leak the filename or mime-type of the other tenant's attachment.
    assert "secret-tenant-a.xlsx" not in response.text
    assert "spreadsheetml" not in response.text


@pytest.mark.asyncio
async def test_attachment_file_same_tenant_returns_200(
    db_session: AsyncSession, two_tenants_with_attachment: dict
):
    attachment_id = two_tenants_with_attachment["attachment"].id
    admin_a = two_tenants_with_attachment["admin_a"]

    client = _make_app(db_session)
    with client, patch(
        "app.api.ingestion.read_file", new=AsyncMock(return_value=b"payload-bytes")
    ):
        response = client.get(
            f"/ingestion/attachments/{attachment_id}/file",
            headers=_auth_headers(admin_a),
        )

    assert response.status_code == 200, response.text
    assert response.content == b"payload-bytes"
    assert 'filename="secret-tenant-a.xlsx"' in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_attachment_full_html_cross_tenant_returns_404(
    db_session: AsyncSession, two_tenants_with_attachment: dict
):
    attachment_id = two_tenants_with_attachment["attachment"].id
    admin_b = two_tenants_with_attachment["admin_b"]

    client = _make_app(db_session)
    with client, patch(
        "app.api.ingestion.read_file", new=AsyncMock(return_value=b"xlsx-bytes")
    ):
        response = client.get(
            f"/ingestion/attachments/{attachment_id}/full-html",
            headers=_auth_headers(admin_b),
        )

    assert response.status_code == 404
    assert "secret-tenant-a.xlsx" not in response.text


@pytest.mark.asyncio
async def test_attachment_full_html_same_tenant_returns_200(
    db_session: AsyncSession, two_tenants_with_attachment: dict
):
    attachment_id = two_tenants_with_attachment["attachment"].id
    admin_a = two_tenants_with_attachment["admin_a"]

    # Inject a stub xlsx_render module so the endpoint's late `from ... import`
    # resolves to our fakes without needing openpyxl installed in the test env.
    import sys
    import types

    stub = types.ModuleType("app.services.xlsx_render")
    stub.render_xlsx_to_html = lambda _bytes, bounded=False: "<table>rendered</table>"
    stub.render_xls_to_html = lambda _bytes, bounded=False: "<table>rendered-xls</table>"
    stub.render_csv_to_html = lambda _bytes: "<table>rendered-csv</table>"
    sys.modules["app.services.xlsx_render"] = stub

    client = _make_app(db_session)
    try:
        with client, patch(
            "app.api.ingestion.read_file", new=AsyncMock(return_value=b"xlsx-bytes")
        ):
            response = client.get(
                f"/ingestion/attachments/{attachment_id}/full-html",
                headers=_auth_headers(admin_a),
            )
    finally:
        sys.modules.pop("app.services.xlsx_render", None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"html": "<table>rendered</table>"}


@pytest.mark.asyncio
async def test_orphaned_attachment_returns_404(
    db_session: AsyncSession, two_tenants_with_attachment: dict
):
    """An EmailAttachment whose email_id references a non-existent row must
    return 404 cleanly — previously relied on attachment.email being lazy-loaded.
    """
    admin_a = two_tenants_with_attachment["admin_a"]

    # Insert via raw SQL to bypass the FK enforcement (on Postgres we would need
    # to set session_replication_role; on SQLite FK is disabled by default, so
    # a direct ORM add works here).
    orphan = EmailAttachment(
        email_id=999999,  # no matching ingested_emails row
        filename="orphan.bin",
        mime_type="application/octet-stream",
        size_bytes=1,
        storage_key="orphan/key",
        extraction_status=ExtractionStatus.completed,
    )
    db_session.add(orphan)
    await db_session.commit()
    orphan_id = orphan.id

    client = _make_app(db_session)
    with client, patch(
        "app.api.ingestion.read_file", new=AsyncMock(return_value=b"xx")
    ):
        response = client.get(
            f"/ingestion/attachments/{orphan_id}/file",
            headers=_auth_headers(admin_a),
        )

    assert response.status_code == 404
