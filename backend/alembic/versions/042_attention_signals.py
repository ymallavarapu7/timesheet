"""Add users.last_login_at + dismissed_attention_signals table.

Revision ID: 042_attention_signals
Revises: 041_service_token_id
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "042_attention_signals"
down_revision = "041_service_token_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "dismissed_attention_signals",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("signal_key", sa.String(length=128), nullable=False),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "signal_key", name="uq_dismissed_user_signal"),
    )


def downgrade() -> None:
    op.drop_table("dismissed_attention_signals")
    op.drop_column("users", "last_login_at")
