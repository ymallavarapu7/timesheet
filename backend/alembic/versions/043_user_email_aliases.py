"""Add user_email_aliases table for ingestion address matching.

Revision ID: 043_user_email_aliases
Revises: 042_attention_signals
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "043_user_email_aliases"
down_revision = "042_attention_signals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_email_aliases",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_user_email_alias_email"),
    )
    op.create_index(
        "ix_user_email_aliases_email_lower",
        "user_email_aliases",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_user_email_aliases_email_lower", table_name="user_email_aliases")
    op.drop_table("user_email_aliases")
