"""Add activity log table for dashboard recent activity.

Revision ID: 004_add_activity_log
Revises: 003_add_ingestion_sync
Create Date: 2026-03-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_add_activity_log"
down_revision: Union[str, None] = "003_add_ingestion_sync"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    inspector = sa.inspect(op.get_bind())
    return any(
        index["name"] == index_name
        for index in inspector.get_indexes(table_name)
    )


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if not _table_exists("activity_log"):
        op.create_table(
            "activity_log",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("actor_name", sa.String(length=255), nullable=True),
            sa.Column("activity_type", sa.String(length=100), nullable=False),
            sa.Column("visibility_scope", sa.String(length=50), nullable=False),
            sa.Column("entity_type", sa.String(length=100), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=True),
            sa.Column("summary", sa.String(length=500), nullable=False),
            sa.Column("route", sa.String(length=255), nullable=False),
            sa.Column("route_params", sa.JSON(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("severity", sa.String(length=20), nullable=False, server_default="info"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_activity_log_tenant_id", "activity_log", ["tenant_id"])
    _create_index_if_missing("ix_activity_log_actor_user_id", "activity_log", ["actor_user_id"])
    _create_index_if_missing("ix_activity_log_activity_type", "activity_log", ["activity_type"])
    _create_index_if_missing("ix_activity_log_visibility_scope", "activity_log", ["visibility_scope"])
    _create_index_if_missing("ix_activity_log_entity_id", "activity_log", ["entity_id"])
    _create_index_if_missing("ix_activity_log_created_at", "activity_log", ["created_at"])


def downgrade() -> None:
    if _table_exists("activity_log"):
        op.drop_table("activity_log")
