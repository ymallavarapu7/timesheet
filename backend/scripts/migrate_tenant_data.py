"""Copy a tenant's data from the shared timesheet_db into its dedicated
acufy_tenant_<slug> database (Phase 3.C.2).

Idempotent. Truncates the target tables (in dependency-respecting order)
and re-INSERTs the source rows that belong to the named tenant. Resets
sequence values at the end so future inserts on the target don't
collide with copied IDs.

This script does NOT flip ``is_isolated`` on the control-plane
``tenants`` row. The resolver still routes every tenant to the shared
DB until that flag is flipped manually after data verification.

Usage::

    docker exec timesheet-api-1 sh -c "cd /app && PYTHONPATH=/app python scripts/migrate_tenant_data.py <slug>"

Prerequisites:
    1. Tenant must be provisioned (``provision_tenant_db.py <slug>``
       run successfully). The target DB exists and is at alembic head
       (``038_schema_drift_catchup`` or later).
    2. Schema drift between source and target must be reconciled.
       Migration 038 handles the known drift; if you've added more
       legacy hand-edits, add another catch-up migration first.

Filter strategy per table:
    * Direct ``tenant_id`` filter on the 17 tenant-scoped tables.
    * Indirect tables (e.g., ``ingestion_timesheet_line_items``,
      ``user_notification_states``, etc.) join through their parent
      to scope by tenant.
    * Global tables (``permissions``, ``setting_definitions``,
      ``platform_settings``) copy in full -- they are tenant-agnostic
      and the per-tenant DB needs the same lookups.
    * ``alembic_version`` is left alone (provisioning set it to head).

Exit codes:
    0  - migration succeeded
    1  - any failure (tenant not found in control plane, target DB
         not provisioned, source query errored, INSERT errored, etc.)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.models.control import ControlTenant


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_tenant_data")


# Tables ordered so that parents come before children. The
# truncate phase walks this list in reverse; the copy phase walks it
# forward.
#
# For each table:
#   filter:
#     "tenant_id"     - WHERE tenant_id = :tid
#     "id"            - WHERE id = :tid (used for `tenants` itself)
#     "all"           - copy every row (global lookup tables)
#     "where:<sql>"   - WHERE <sql>; the snippet may reference :tid
#                       directly. Used for tables with composite PKs
#                       or where filtering through the parent FK is
#                       cleaner than an id-based IN clause.
# Nullable FK columns that point at users.id and may legitimately
# reference an actor outside the tenant (e.g., a PLATFORM_ADMIN who
# performed an action). On copy, if the target id is not in the
# tenant's user set, we set the column to NULL so the FK constraint
# holds without losing the surrounding row.
#
# Only nullable user-FK columns belong here. NOT NULL FKs would not
# survive being nulled, and in practice they always point inside the
# tenant on the source DB.
NULLABLE_USER_FKS: dict[str, tuple[str, ...]] = {
    "activity_log": ("actor_user_id",),
    "ingestion_audit_log": ("user_id",),
    "ingestion_timesheets": ("employee_id", "reviewer_id"),
    "role_assignments": ("granted_by",),
    "time_entries": ("approved_by", "created_by", "updated_by"),
    "time_off_requests": ("approved_by", "created_by", "updated_by"),
}


TABLES: list[tuple[str, str]] = [
    # Globals first -- nothing references them by tenant.
    ("permissions", "all"),
    ("setting_definitions", "all"),
    ("platform_settings", "all"),

    # The tenant row itself, then its direct children.
    ("tenants", "id"),
    ("tenant_settings", "tenant_id"),
    ("departments", "tenant_id"),
    ("clients", "tenant_id"),
    ("client_email_domains", "tenant_id"),
    ("projects", "tenant_id"),
    ("tasks", "tenant_id"),

    # Users and their auth artifacts.
    ("users", "tenant_id"),
    ("refresh_tokens",
     "where:user_id IN (SELECT id FROM users WHERE tenant_id = :tid)"),
    ("employee_manager_assignments",
     "where:employee_id IN (SELECT id FROM users WHERE tenant_id = :tid)"),
    ("user_project_access",
     "where:user_id IN (SELECT id FROM users WHERE tenant_id = :tid)"),
    ("user_notification_states",
     "where:user_id IN (SELECT id FROM users WHERE tenant_id = :tid)"),
    ("user_notification_dismissals",
     "where:user_id IN (SELECT id FROM users WHERE tenant_id = :tid)"),

    # Roles and assignments. The seven system roles in the live DB
    # carry tenant_id IS NULL (they're global) -- include them in
    # every tenant's copy or role_assignments breaks. Assignments
    # join through users.
    ("roles", "where:tenant_id = :tid OR tenant_id IS NULL"),
    ("role_permissions",
     "where:role_id IN (SELECT id FROM roles WHERE tenant_id = :tid OR tenant_id IS NULL)"),
    ("role_assignments",
     "where:user_id IN (SELECT id FROM users WHERE tenant_id = :tid)"),

    # Time tracking.
    ("leave_types", "tenant_id"),
    ("time_entries", "tenant_id"),
    ("time_entry_edit_history",
     "where:time_entry_id IN (SELECT id FROM time_entries WHERE tenant_id = :tid)"),
    ("time_off_requests", "tenant_id"),

    # Ingestion pipeline.
    ("mailboxes", "tenant_id"),
    ("ingested_emails", "tenant_id"),
    ("email_attachments",
     "where:email_id IN (SELECT id FROM ingested_emails WHERE tenant_id = :tid)"),
    ("ingestion_timesheets", "tenant_id"),
    ("ingestion_timesheet_line_items",
     "where:ingestion_timesheet_id IN "
     "(SELECT id FROM ingestion_timesheets WHERE tenant_id = :tid)"),
    ("ingestion_audit_log",
     "where:ingestion_timesheet_id IN "
     "(SELECT id FROM ingestion_timesheets WHERE tenant_id = :tid)"),

    # Audit / housekeeping.
    ("activity_log", "tenant_id"),
    ("sync_log", "tenant_id"),
    ("service_tokens", "tenant_id"),
]


def _tenant_db_name(slug: str) -> str:
    return f"acufy_tenant_{slug}"


def _tenant_db_url(db_name: str) -> str:
    base = urlparse(settings.database_url)
    return f"{base.scheme}://{base.netloc}/{db_name}"


async def _column_info(conn: Any, table: str) -> list[tuple[str, str]]:
    """Read (column_name, udt_name) in ordinal order from
    information_schema. udt_name is the Postgres type identifier (e.g.,
    ``int4``, ``jsonb``, ``timestamptz``). We intentionally don't rely
    on SQLAlchemy reflection: the source schema may have legacy columns
    that the model declarations don't list, and we want a verbatim
    copy."""
    result = await conn.execute(
        text(
            "SELECT column_name, udt_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t "
            "ORDER BY ordinal_position"
        ),
        {"t": table},
    )
    return [(row[0], row[1]) for row in result.fetchall()]


def _json_columns(cols: list[tuple[str, str]]) -> set[str]:
    """Names of columns whose udt is json or jsonb. asyncpg's positional
    parameter binding treats these as text; we have to re-serialize
    Python values (dicts, lists, ints, bools) to JSON strings before
    insert. SQLAlchemy's JSON type would handle this automatically if
    we built INSERTs through Core constructs, but we use textual SQL
    for speed and column-list flexibility."""
    return {name for name, udt in cols if udt in ("json", "jsonb")}


async def _fetch_source_rows(
    src_conn: Any,
    table: str,
    cols: list[tuple[str, str]],
    filter_spec: str,
    tenant_id: int,
) -> list[dict[str, Any]]:
    col_list = ", ".join(f'"{c}"' for c, _ in cols)
    if filter_spec == "all":
        sql = f'SELECT {col_list} FROM "{table}"'
        params: dict[str, Any] = {}
    elif filter_spec == "tenant_id":
        sql = f'SELECT {col_list} FROM "{table}" WHERE tenant_id = :tid'
        params = {"tid": tenant_id}
    elif filter_spec == "id":
        sql = f'SELECT {col_list} FROM "{table}" WHERE id = :tid'
        params = {"tid": tenant_id}
    elif filter_spec.startswith("where:"):
        where_clause = filter_spec[len("where:"):]
        sql = f'SELECT {col_list} FROM "{table}" WHERE {where_clause}'
        params = {"tid": tenant_id}
    else:  # pragma: no cover - guarded by config above
        raise ValueError(f"unknown filter spec: {filter_spec}")
    result = await src_conn.execute(text(sql), params)
    return [dict(row._mapping) for row in result.fetchall()]


async def _truncate_targets(tgt_conn: Any) -> None:
    """TRUNCATE every table in TABLES in reverse order with CASCADE.
    CASCADE handles any FK cycles or stragglers without us having to
    worry about ordering edge cases."""
    table_list = ", ".join(f'"{t}"' for t, _ in TABLES)
    await tgt_conn.execute(
        text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")
    )


async def _insert_rows(
    tgt_conn: Any,
    table: str,
    cols: list[tuple[str, str]],
    rows: list[dict[str, Any]],
    valid_user_ids: set[int] | None = None,
) -> int:
    if not rows:
        return 0
    col_names = [c for c, _ in cols]
    json_cols = _json_columns(cols)
    nullable_user_fks = NULLABLE_USER_FKS.get(table, ())
    if json_cols or (nullable_user_fks and valid_user_ids is not None):
        # Mutate a copy so the original payload (held by the caller for
        # logging) stays untouched.
        cleaned: list[dict[str, Any]] = []
        for row in rows:
            new_row: dict[str, Any] = {}
            for k, v in row.items():
                if (
                    k in nullable_user_fks
                    and v is not None
                    and valid_user_ids is not None
                    and v not in valid_user_ids
                ):
                    new_row[k] = None
                elif k in json_cols and v is not None:
                    new_row[k] = json.dumps(v)
                else:
                    new_row[k] = v
            cleaned.append(new_row)
        rows = cleaned
    col_list = ", ".join(f'"{c}"' for c in col_names)
    placeholders = ", ".join(f":{c}" for c in col_names)
    sql = f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})'
    await tgt_conn.execute(text(sql), rows)
    return len(rows)


async def _reset_sequences(tgt_conn: Any) -> int:
    """For each table with an integer ``id`` column backed by a
    sequence, set the sequence to MAX(id). Without this, the first
    INSERT after the migration could collide with a copied id."""
    result = await tgt_conn.execute(text("""
        SELECT t.table_name, pg_get_serial_sequence('public.'||t.table_name, c.column_name) AS seq
        FROM information_schema.tables t
        JOIN information_schema.columns c
          ON c.table_schema=t.table_schema AND c.table_name=t.table_name
        WHERE t.table_schema='public' AND t.table_type='BASE TABLE'
          AND c.column_name='id'
          AND pg_get_serial_sequence('public.'||t.table_name, c.column_name) IS NOT NULL
        ORDER BY t.table_name
    """))
    rows = result.fetchall()
    n = 0
    for table_name, seq in rows:
        # Use is_called=true when the table has rows (next nextval gives
        # MAX+1); is_called=false when empty (next gives 1).
        await tgt_conn.execute(text(f"""
            SELECT setval('{seq}',
                COALESCE((SELECT MAX(id) FROM "{table_name}"), 1),
                (SELECT COUNT(*) > 0 FROM "{table_name}"))
        """))
        n += 1
    return n


async def _resolve_tenant_id(slug: str) -> int:
    """Look up the tenant's id on the control plane. The id is the
    primary key the source DB also uses (3.A migrated rows preserving
    ids), so we filter source by this same value."""
    engine = create_async_engine(settings.control_database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            tenant = (await session.execute(
                select(ControlTenant).where(ControlTenant.slug == slug)
            )).scalar_one_or_none()
            if tenant is None:
                raise SystemExit(
                    f"tenant slug={slug!r} not found in acufy_control.tenants. "
                    "Run scripts/provision_tenant_db.py first."
                )
            if tenant.db_name is None:
                raise SystemExit(
                    f"tenant {slug!r} has no db_name set on control plane. "
                    "Run scripts/provision_tenant_db.py first."
                )
            return tenant.id
    finally:
        await engine.dispose()


async def _migrate(slug: str, dry_run: bool) -> int:
    tenant_id = await _resolve_tenant_id(slug)
    db_name = _tenant_db_name(slug)
    src_url = settings.database_url
    tgt_url = _tenant_db_url(db_name)

    logger.info("source: %s", urlparse(src_url).path)
    logger.info("target: %s", urlparse(tgt_url).path)
    logger.info("tenant: slug=%s id=%d", slug, tenant_id)

    src_engine = create_async_engine(src_url)
    tgt_engine = create_async_engine(tgt_url)
    total_rows = 0
    try:
        # Read every source table first (within a single read snapshot)
        # then write to the target. Keeping read and write transactions
        # separate avoids holding a long lock on the live shared DB.
        per_table_payload: list[
            tuple[str, list[tuple[str, str]], list[dict[str, Any]]]
        ] = []
        valid_user_ids: set[int] = set()
        async with src_engine.connect() as src_conn:
            for table, filter_spec in TABLES:
                cols = await _column_info(src_conn, table)
                rows = await _fetch_source_rows(
                    src_conn, table, cols, filter_spec, tenant_id
                )
                per_table_payload.append((table, cols, rows))
                if table == "users":
                    valid_user_ids = {r["id"] for r in rows}
                logger.info("  read %-32s %d rows", table, len(rows))
                total_rows += len(rows)

        if dry_run:
            logger.info("dry-run: read %d rows total, no writes", total_rows)
            return 0

        async with tgt_engine.begin() as tgt_conn:
            await _truncate_targets(tgt_conn)
            for table, cols, rows in per_table_payload:
                inserted = await _insert_rows(
                    tgt_conn, table, cols, rows, valid_user_ids
                )
                if inserted:
                    logger.info("  wrote %-32s %d rows", table, inserted)
            seq_count = await _reset_sequences(tgt_conn)
            logger.info("reset %d sequences", seq_count)

        logger.info("done: %d rows copied for slug=%s", total_rows, slug)
        return 0
    finally:
        await src_engine.dispose()
        await tgt_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", help="tenant slug (must exist in acufy_control.tenants)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="read source rows but do not modify the target DB",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_migrate(args.slug, args.dry_run)))


if __name__ == "__main__":
    main()
