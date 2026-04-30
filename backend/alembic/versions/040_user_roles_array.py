"""Add users.roles JSONB list, backfill from role.

Revision ID: 040_user_roles_array
Revises: 039_user_linked_account
Create Date: 2026-04-30

Background:
    Phase 3.C role-split shipped on the assumption that a human who is
    both an admin and a manager keeps two separate accounts (linked via
    users.linked_user_id, with cross-portal handoff). That model is
    wrong: real humans have one email and one password. We are moving
    to one User per human with a list of allowed roles; the existing
    role column becomes the *currently active* role.

This migration:
    - Adds users.roles JSONB NOT NULL DEFAULT '[]'.
    - Backfills every existing row's roles to a one-element list
      containing the current role. Read-modify-write is unnecessary
      because role is single-valued today.

Backwards compat: every existing piece of code reads current_user.role,
which is unchanged. New code that needs "what roles is this user
allowed to act as" reads current_user.roles. No drop in this migration.

Linked accounts: users.linked_user_id stays in the schema. A follow-up
migration (after the multi-role rollout has soaked) will drop it once
we confirm no one is using the old handoff path.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "040_user_roles_array"
down_revision = "039_user_linked_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "roles",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # Backfill: roles = [role::text] for every existing user. We use a
    # raw SQL update because the SQLAlchemy enum binding for the role
    # column doesn't help us inside a migration.
    op.execute(
        "UPDATE users SET roles = jsonb_build_array(role::text) "
        "WHERE roles = '[]'::jsonb"
    )


def downgrade() -> None:
    op.drop_column("users", "roles")
