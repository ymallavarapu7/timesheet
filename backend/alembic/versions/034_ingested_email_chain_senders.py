"""Add chain_senders JSONB column on ingested_emails

Revision ID: 034_chain_senders
Revises: 031_permission_framework
Create Date: 2026-04-23

Stores every distinct (name, email) pair we could pull from the forward
chain — nested message/rfc822 parts and body-quoted "From:" lines — so
the review UI can offer them as employee candidates when no existing
user matches the outer sender. See app.services.email_parser for the
extraction logic and app.services.ingestion_pipeline for the matching
rules that decide when to auto-assign vs surface candidates.

Additive: backfilled to NULL for existing rows. Never rewrites
forwarded_from_email / forwarded_from_name, which remain the "nearest
upstream sender" signal.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "034_chain_senders"
down_revision = "031_permission_framework"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingested_emails",
        sa.Column(
            "chain_senders",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("ingested_emails", "chain_senders")
