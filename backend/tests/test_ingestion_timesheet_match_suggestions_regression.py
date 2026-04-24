"""
Regression test for the NameError caused by an orphaned reference to
`match_suggestions` in ingestion_pipeline._process_timesheet_attachment.

Commit 317fc13 removed the match_entities() LLM call (and the helper that
produced `match_suggestions`) but left `llm_match_suggestions=match_suggestions`
behind in the IngestionTimesheet constructor — every email that reached that
step raised NameError, so ingestion silently failed.

This test guards two things:
  1. The function body no longer references an undefined `match_suggestions`.
  2. An IngestionTimesheet can be created without specifying
     llm_match_suggestions, and the column persists as NULL.
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from textwrap import dedent

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - test shim
    return "JSON"


from app.models.base import Base
from app.models.ingested_email import IngestedEmail
from app.models.ingestion_timesheet import IngestionTimesheet, IngestionTimesheetStatus
from app.models.mailbox import Mailbox, MailboxAuthType, MailboxProtocol
from app.models.tenant import Tenant, TenantStatus
from app.services import ingestion_pipeline


@pytest_asyncio.fixture
async def db_session(tmp_path) -> AsyncSession:
    db_file = tmp_path / "ingestion_match_suggestions.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _free_names_in_function(func) -> set[str]:
    """
    Return Name loads in `func` that aren't bound by its args or top-level
    assignments.

    Limitation: this walker doesn't track scopes for comprehensions or nested
    functions — names bound only inside those inner scopes are not added to
    `bound`. That's acceptable for the regression this test guards (a plain
    assignment that got deleted): any reintroduction of `match_suggestions` as
    a straightforward top-level reference will still be caught.
    """
    src = dedent(inspect.getsource(func))
    tree = ast.parse(src)
    func_node = tree.body[0]
    assert isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef))

    bound: set[str] = set()
    for arg in (
        list(func_node.args.args)
        + list(func_node.args.kwonlyargs)
        + list(func_node.args.posonlyargs)
    ):
        bound.add(arg.arg)
    if func_node.args.vararg:
        bound.add(func_node.args.vararg.arg)
    if func_node.args.kwarg:
        bound.add(func_node.args.kwarg.arg)
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        bound.add(sub.id)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)):
            if isinstance(node.target, ast.Name):
                bound.add(node.target.id)
        elif isinstance(node, ast.For):
            for sub in ast.walk(node.target):
                if isinstance(sub, ast.Name):
                    bound.add(sub.id)

    loaded: set[str] = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loaded.add(node.id)

    return loaded - bound


def test_match_suggestions_not_referenced_as_free_variable():
    """
    Directly catches a reintroduction of the orphaned `match_suggestions`
    reference. If someone adds back `llm_match_suggestions=match_suggestions`
    without also defining `match_suggestions`, this test fails.
    """
    free = _free_names_in_function(ingestion_pipeline._process_timesheet_attachment)
    assert "match_suggestions" not in free, (
        "`match_suggestions` is referenced in _process_timesheet_attachment "
        "but not defined in its scope — this is the exact NameError regression "
        "that caused ingestion to silently fail. If you need match suggestions, "
        "compute and assign the variable before constructing IngestionTimesheet."
    )


@pytest.mark.asyncio
async def test_ingestion_timesheet_persists_without_match_suggestions(
    db_session: AsyncSession,
):
    """
    The `llm_match_suggestions` column must remain nullable so that
    IngestionTimesheet rows created without chain-candidate data persist
    cleanly with NULL. The original bug fix removed an undefined
    `match_suggestions` reference; this test confirms the column still
    works unset, which is the default path when a row isn't a forward
    chain that needs reviewer disambiguation.
    """
    tenant = Tenant(
        name="Tenant M",
        slug="tenant-m",
        status=TenantStatus.active,
        ingestion_enabled=True,
    )
    db_session.add(tenant)
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
        message_id="<match-suggestions-regression>",
        sender_email="ts@example.com",
        subject="Timesheet",
        received_at=datetime.now(timezone.utc),
    )
    db_session.add(email)
    await db_session.flush()

    ts = IngestionTimesheet(
        tenant_id=tenant.id,
        email_id=email.id,
        status=IngestionTimesheetStatus.pending,
        extracted_data={"employee_name": "Jane"},
        llm_anomalies={"items": []},
        # NOTE: deliberately omitting llm_match_suggestions — this is the
        # shape the production code now uses.
    )
    db_session.add(ts)
    await db_session.commit()
    await db_session.refresh(ts)

    assert ts.id is not None
    assert ts.llm_match_suggestions is None
