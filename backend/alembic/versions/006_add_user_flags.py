"""Add reviewer and external-user flags.

Revision ID: 006_add_user_flags
Revises: 005_add_tenant_ingestion_flag
Create Date: 2026-03-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_add_user_flags"
down_revision: Union[str, None] = "005_add_tenant_ingestion_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        column["name"] == column_name
        for column in inspector.get_columns(table_name)
    )


def upgrade() -> None:
    if not _column_exists("users", "can_review"):
        op.add_column(
            "users",
            sa.Column(
                "can_review",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
        )
    if not _column_exists("users", "is_external"):
        op.add_column(
            "users",
            sa.Column(
                "is_external",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
        )


def downgrade() -> None:
    if _column_exists("users", "can_review"):
        op.drop_column("users", "can_review")
    if _column_exists("users", "is_external"):
        op.drop_column("users", "is_external")
