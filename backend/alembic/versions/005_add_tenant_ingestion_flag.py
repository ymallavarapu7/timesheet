"""Add tenant ingestion capability flag.

Revision ID: 005_add_tenant_ingestion_flag
Revises: 004_add_activity_log
Create Date: 2026-03-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_add_tenant_ingestion_flag"
down_revision: Union[str, None] = "004_add_activity_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        column["name"] == column_name
        for column in inspector.get_columns(table_name)
    )


def upgrade() -> None:
    if not _column_exists("tenants", "ingestion_enabled"):
        op.add_column(
            "tenants",
            sa.Column(
                "ingestion_enabled",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
        )


def downgrade() -> None:
    if _column_exists("tenants", "ingestion_enabled"):
        op.drop_column("tenants", "ingestion_enabled")
