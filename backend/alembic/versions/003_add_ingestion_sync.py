"""Add ingestion platform sync: cross-reference columns, sync_log, service_tokens tables.

Revision ID: 003_add_ingestion_sync
Revises: 002_add_multi_tenancy
Create Date: 2026-03-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_add_ingestion_sync"
down_revision: Union[str, None] = "002_add_multi_tenancy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(
        column["name"] == column_name
        for column in _inspector().get_columns(table_name)
    )


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(
        index["name"] == index_name
        for index in _inspector().get_indexes(table_name)
    )


def _enum_exists(enum_name: str) -> bool:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return False
    return any(
        enum["name"] == enum_name
        for enum in _inspector().get_enums()
    )


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _column_exists(table_name, column_name):
        op.drop_column(table_name, column_name)


def _ensure_postgres_enum(enum_name: str, values: list[str]) -> None:
    if _enum_exists(enum_name):
        return

    quoted_values = ", ".join(f"'{value}'" for value in values)
    op.execute(
        sa.text(f"CREATE TYPE {enum_name} AS ENUM ({quoted_values})")
    )


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Cross-reference columns on users
    _add_column_if_missing(
        "users",
        sa.Column("ingestion_employee_id", sa.String(36), nullable=True),
    )
    _add_column_if_missing(
        "users",
        sa.Column("ingestion_created_by", sa.String(255), nullable=True),
    )
    _create_index_if_missing(
        "ix_users_ingestion_employee_id",
        "users",
        ["ingestion_employee_id"],
    )

    # Cross-reference columns on clients
    _add_column_if_missing(
        "clients",
        sa.Column("ingestion_client_id", sa.String(36), nullable=True),
    )
    _create_index_if_missing(
        "ix_clients_ingestion_client_id",
        "clients",
        ["ingestion_client_id"],
    )

    # Cross-reference columns on projects
    _add_column_if_missing(
        "projects",
        sa.Column("ingestion_project_id", sa.String(36), nullable=True),
    )
    _create_index_if_missing(
        "ix_projects_ingestion_project_id",
        "projects",
        ["ingestion_project_id"],
    )

    # Cross-reference columns on time_entries
    _add_column_if_missing(
        "time_entries",
        sa.Column("ingestion_timesheet_id", sa.String(36), nullable=True),
    )
    _add_column_if_missing(
        "time_entries",
        sa.Column("ingestion_line_item_id", sa.String(36), nullable=True),
    )
    _add_column_if_missing(
        "time_entries",
        sa.Column("ingestion_approved_by_name", sa.String(255), nullable=True),
    )
    _add_column_if_missing(
        "time_entries",
        sa.Column("ingestion_source_tenant", sa.String(255), nullable=True),
    )
    _create_index_if_missing(
        "ix_time_entries_ingestion_timesheet_id",
        "time_entries",
        ["ingestion_timesheet_id"],
    )
    _create_index_if_missing(
        "ix_time_entries_ingestion_line_item_id",
        "time_entries",
        ["ingestion_line_item_id"],
    )

    if dialect == "postgresql":
        _ensure_postgres_enum("syncdirection", ["inbound", "outbound"])
        _ensure_postgres_enum(
            "syncentitytype",
            ["user", "client", "project", "time_entry", "timesheet"],
        )
        _ensure_postgres_enum(
            "syncstatus",
            ["success", "failed", "skipped", "partial"],
        )

        sync_direction = postgresql.ENUM(
            "inbound",
            "outbound",
            name="syncdirection",
            create_type=False,
        )
        sync_entity_type = postgresql.ENUM(
            "user",
            "client",
            "project",
            "time_entry",
            "timesheet",
            name="syncentitytype",
            create_type=False,
        )
        sync_status = postgresql.ENUM(
            "success",
            "failed",
            "skipped",
            "partial",
            name="syncstatus",
            create_type=False,
        )
    else:
        sync_direction = sa.Enum("inbound", "outbound", name="syncdirection")
        sync_entity_type = sa.Enum(
            "user",
            "client",
            "project",
            "time_entry",
            "timesheet",
            name="syncentitytype",
        )
        sync_status = sa.Enum(
            "success",
            "failed",
            "skipped",
            "partial",
            name="syncstatus",
        )

    # sync_log table
    if not _table_exists("sync_log"):
        op.create_table(
            "sync_log",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id"),
                nullable=False,
            ),
            sa.Column("direction", sync_direction, nullable=False),
            sa.Column("entity_type", sync_entity_type, nullable=False),
            sa.Column("local_id", sa.Integer(), nullable=True),
            sa.Column("ingestion_id", sa.String(36), nullable=True),
            sa.Column("status", sync_status, nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("payload", sa.Text(), nullable=True),
            sa.Column("action", sa.String(50), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_sync_log_tenant_id", "sync_log", ["tenant_id"])
    _create_index_if_missing(
        "ix_sync_log_ingestion_id",
        "sync_log",
        ["ingestion_id"],
    )

    # service_tokens table
    if not _table_exists("service_tokens"):
        op.create_table(
            "service_tokens",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("token_hash", sa.String(255), nullable=False),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id"),
                nullable=False,
            ),
            sa.Column("issuer", sa.String(100), nullable=False),
            sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
            sa.Column("last_used_at", sa.String(50), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(
        "ix_service_tokens_tenant_id",
        "service_tokens",
        ["tenant_id"],
    )


def downgrade() -> None:
    _drop_index_if_exists("ix_service_tokens_tenant_id", "service_tokens")
    if _table_exists("service_tokens"):
        op.drop_table("service_tokens")

    _drop_index_if_exists("ix_sync_log_ingestion_id", "sync_log")
    _drop_index_if_exists("ix_sync_log_tenant_id", "sync_log")
    if _table_exists("sync_log"):
        op.drop_table("sync_log")

    _drop_index_if_exists(
        "ix_time_entries_ingestion_line_item_id",
        "time_entries",
    )
    _drop_index_if_exists(
        "ix_time_entries_ingestion_timesheet_id",
        "time_entries",
    )
    for column_name in [
        "ingestion_timesheet_id",
        "ingestion_line_item_id",
        "ingestion_approved_by_name",
        "ingestion_source_tenant",
    ]:
        _drop_column_if_exists("time_entries", column_name)

    _drop_index_if_exists(
        "ix_projects_ingestion_project_id",
        "projects",
    )
    _drop_column_if_exists("projects", "ingestion_project_id")

    _drop_index_if_exists(
        "ix_clients_ingestion_client_id",
        "clients",
    )
    _drop_column_if_exists("clients", "ingestion_client_id")

    _drop_index_if_exists(
        "ix_users_ingestion_employee_id",
        "users",
    )
    _drop_column_if_exists("users", "ingestion_employee_id")
    _drop_column_if_exists("users", "ingestion_created_by")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS syncstatus")
        op.execute("DROP TYPE IF EXISTS syncentitytype")
        op.execute("DROP TYPE IF EXISTS syncdirection")
