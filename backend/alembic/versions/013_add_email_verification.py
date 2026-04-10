"""Add email verification fields to users table.

Revision ID: 013_add_email_verification
Revises: 012_refresh_tokens
Create Date: 2026-04-07
"""

from alembic import op
import sqlalchemy as sa

revision = "013_add_email_verification"
down_revision = "012_refresh_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add with server_default="false" so the column is non-nullable from the start.
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("email_verification_token", sa.String(128), nullable=True))
    op.add_column("users", sa.Column("email_verification_token_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_email_verification_token", "users", ["email_verification_token"], unique=True)

    # All users that existed before this migration are treated as already verified
    # so they are not locked out after upgrading.
    op.execute("UPDATE users SET email_verified = true WHERE email_verified = false")


def downgrade() -> None:
    op.drop_index("ix_users_email_verification_token", table_name="users")
    op.drop_column("users", "email_verification_token_expires_at")
    op.drop_column("users", "email_verification_token")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
