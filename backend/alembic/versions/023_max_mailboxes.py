"""Add max_mailboxes cap on tenants; backfill ingestion-enabled tenants to 1

Revision ID: 023_max_mailboxes
Revises: 022_leave_types
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "023_max_mailboxes"
down_revision = "022_leave_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("max_mailboxes", sa.Integer(), nullable=True),
    )

    # Backfill: for every ingestion-enabled tenant, set max_mailboxes to the
    # greater of (current active mailbox count, 1). Tenants that already have
    # multiple mailboxes aren't retroactively broken; platform admin can lower
    # the cap later.
    op.execute(
        """
        UPDATE tenants t
        SET max_mailboxes = GREATEST(
            (SELECT COUNT(*) FROM mailboxes m WHERE m.tenant_id = t.id AND m.is_active = TRUE),
            1
        )
        WHERE t.ingestion_enabled = TRUE;
        """
    )


def downgrade() -> None:
    op.drop_column("tenants", "max_mailboxes")
