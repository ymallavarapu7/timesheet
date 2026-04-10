"""Add is_rejected and rejection_reason to ingestion_timesheet_line_items.

Revision ID: 009_add_line_item_rejection
Revises: 008_add_graph_mailbox_protocol
Create Date: 2026-04-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_add_line_item_rejection"
down_revision: Union[str, None] = "008_add_graph_mailbox_protocol"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingestion_timesheet_line_items",
        sa.Column("is_rejected", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "ingestion_timesheet_line_items",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingestion_timesheet_line_items", "rejection_reason")
    op.drop_column("ingestion_timesheet_line_items", "is_rejected")
