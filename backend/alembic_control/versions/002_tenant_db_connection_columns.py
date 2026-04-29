"""Add per-tenant database connection columns to acufy_control.tenants.

Phase 3.C.1: the control-plane ``tenants`` row gains the connection
details for each tenant's dedicated database, plus an ``is_isolated``
flag that the resolver uses as a cutover switch. While ``is_isolated``
is False (the default for existing rows) the tenant continues to read
and write against the shared ``timesheet_db``; flipping it to True
routes traffic to the per-tenant database.

Columns are nullable: tenants that haven't been provisioned yet have
no connection details, and the resolver falls back to the shared DB.

Revision ID: 002_tenant_db_connection
Revises: 001_initial_control
Create Date: 2026-04-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_tenant_db_connection"
down_revision: Union[str, None] = "001_initial_control"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("db_name", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("db_host", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("db_port", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("db_user_enc", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("db_password_enc", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "is_isolated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "is_isolated")
    op.drop_column("tenants", "db_password_enc")
    op.drop_column("tenants", "db_user_enc")
    op.drop_column("tenants", "db_port")
    op.drop_column("tenants", "db_host")
    op.drop_column("tenants", "db_name")
