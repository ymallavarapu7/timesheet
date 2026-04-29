"""Initial control-plane schema.

Creates the four control-plane tables:
- tenants            : tenant directory
- platform_admins    : PLATFORM_ADMIN auth records
- platform_settings  : platform-wide key/value settings
- tenant_provisioning_jobs : audit log of provisioning runs

Revision ID: 001_initial_control
Revises:
Create Date: 2026-04-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial_control"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", "suspended", name="control_tenant_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "ingestion_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("max_mailboxes", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
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
    )
    op.create_index(
        "ix_tenants_slug", "tenants", ["slug"], unique=True
    )

    op.create_table(
        "platform_admins",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "has_changed_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
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
    )
    op.create_index(
        "ix_platform_admins_email", "platform_admins", ["email"], unique=True
    )
    op.create_index(
        "ix_platform_admins_username", "platform_admins", ["username"], unique=True
    )

    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
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
    )
    op.create_index(
        "ix_platform_settings_key", "platform_settings", ["key"], unique=True
    )

    op.create_table(
        "tenant_provisioning_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum("create", "migrate", "deactivate", name="provisioning_job_kind"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "running", "succeeded", "failed",
                name="provisioning_job_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alembic_revision", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
    )
    op.create_index(
        "ix_tenant_provisioning_jobs_tenant_id",
        "tenant_provisioning_jobs",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_provisioning_jobs_tenant_id",
        table_name="tenant_provisioning_jobs",
    )
    op.drop_table("tenant_provisioning_jobs")
    op.drop_index("ix_platform_settings_key", table_name="platform_settings")
    op.drop_table("platform_settings")
    op.drop_index("ix_platform_admins_username", table_name="platform_admins")
    op.drop_index("ix_platform_admins_email", table_name="platform_admins")
    op.drop_table("platform_admins")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
    # Drop the enums Postgres created. SQLite ignores Enum drops.
    sa.Enum(name="provisioning_job_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="provisioning_job_kind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="control_tenant_status").drop(op.get_bind(), checkfirst=True)
