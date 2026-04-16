"""Custom leave types: add leave_types table; migrate time_off_requests.leave_type to varchar

Revision ID: 022_leave_types
Revises: 021_departments
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "022_leave_types"
down_revision = "021_departments"
branch_labels = None
depends_on = None


DEFAULT_LEAVE_TYPES = [
    ("SICK_DAY", "Sick Day", "#ef4444"),
    ("PTO", "PTO", "#10b981"),
    ("HALF_DAY", "Half Day", "#f59e0b"),
    ("HOURLY_PERMISSION", "Hourly Permission", "#6366f1"),
    ("OTHER_LEAVE", "Other Leave", "#6b7280"),
]


def upgrade() -> None:
    # 1. Create leave_types table.
    op.create_table(
        "leave_types",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=20), nullable=False, server_default="#6b7280"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_leave_types_tenant_code"),
    )
    op.create_index("ix_leave_types_tenant_id", "leave_types", ["tenant_id"])

    # 2. Seed default 5 leave types for every existing tenant.
    for code, label, color in DEFAULT_LEAVE_TYPES:
        op.execute(
            f"""
            INSERT INTO leave_types (tenant_id, code, label, color, is_active, created_at, updated_at)
            SELECT id, '{code}', '{label}', '{color}', TRUE, NOW(), NOW() FROM tenants
            ON CONFLICT (tenant_id, code) DO NOTHING;
            """
        )

    # 3. Alter time_off_requests.leave_type: enum -> varchar(50).
    #    Use USING to cast the enum value to its text representation.
    op.execute(
        "ALTER TABLE time_off_requests "
        "ALTER COLUMN leave_type TYPE VARCHAR(50) "
        "USING leave_type::text;"
    )

    # 4. Drop the now-unused Postgres enum type if nothing else references it.
    op.execute("DROP TYPE IF EXISTS timeofftype;")


def downgrade() -> None:
    # Re-create the enum and convert column back. Any custom leave types beyond
    # the original 5 will fail this cast — call out in release notes.
    op.execute(
        "CREATE TYPE timeofftype AS ENUM ('SICK_DAY', 'PTO', 'HALF_DAY', 'HOURLY_PERMISSION', 'OTHER_LEAVE');"
    )
    op.execute(
        "ALTER TABLE time_off_requests "
        "ALTER COLUMN leave_type TYPE timeofftype "
        "USING leave_type::timeofftype;"
    )
    op.drop_index("ix_leave_types_tenant_id", table_name="leave_types")
    op.drop_table("leave_types")
