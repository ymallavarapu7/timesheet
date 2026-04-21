"""Create permission framework tables and seed them.

Revision ID: 031_permission_framework
Revises: 030_seed_tenant_timezone_setting
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

from app.seed_permissions import seed_sync

revision = "031_permission_framework"
down_revision = "030_seed_tenant_timezone_setting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("code", sa.String(length=100), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.UniqueConstraint("tenant_id", "code", name="uq_roles_tenant_id_code"),
    )
    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "permission_code",
            sa.String(length=100),
            sa.ForeignKey("permissions.code", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_code"),
    )
    op.create_table(
        "role_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scope_type",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'tenant'"),
        ),
        sa.Column("scope_ref_id", sa.Integer(), nullable=True),
        sa.Column(
            "effective_from",
            sa.Date(),
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "granted_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id",
            "role_id",
            "effective_from",
            name="uq_role_assignments_user_role_from",
        ),
    )
    op.create_index("ix_role_assignments_user_id", "role_assignments", ["user_id"])
    op.create_index(
        "ix_role_assignments_effective_to",
        "role_assignments",
        ["effective_to"],
    )
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"])

    seed_sync(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_roles_tenant_id", table_name="roles")
    op.drop_index("ix_role_assignments_effective_to", table_name="role_assignments")
    op.drop_index("ix_role_assignments_user_id", table_name="role_assignments")
    op.drop_table("role_assignments")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("permissions")
