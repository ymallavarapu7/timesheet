"""Create licensing tables and tenant fields.

Revision ID: 032_licensing
Revises: 031_permission_framework
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "032_licensing"
down_revision = "031_permission_framework"
branch_labels = None
depends_on = None


def upgrade() -> None:
    features_type = sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )

    op.create_table(
        "issued_licenses",
        sa.Column("jti", sa.String(length=64), primary_key=True),
        sa.Column("tenant_name", sa.String(length=200), nullable=False),
        sa.Column("server_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "tier",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'enterprise'"),
        ),
        sa.Column(
            "max_users",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "features",
            features_type,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "issued_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_mode", sa.String(length=20), nullable=True),
        sa.Column("last_verified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_active_users", sa.Integer(), nullable=True),
        sa.Column("last_version", sa.String(length=30), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.add_column(
        "tenants",
        sa.Column(
            "deployment_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'saas'"),
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "license_expiry_behavior",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'read_only'"),
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("license_jti", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("license_grace_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tenants_license_jti_issued_licenses",
        "tenants",
        "issued_licenses",
        ["license_jti"],
        ["jti"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_tenants_license_jti_issued_licenses",
        "tenants",
        type_="foreignkey",
    )
    op.drop_column("tenants", "license_grace_until")
    op.drop_column("tenants", "license_jti")
    op.drop_column("tenants", "license_expiry_behavior")
    op.drop_column("tenants", "deployment_type")
    op.drop_table("issued_licenses")
