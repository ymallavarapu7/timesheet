"""Add users.linked_user_id for cross-portal handoff.

Revision ID: 039_user_linked_account
Revises: 038_schema_drift_catchup
Create Date: 2026-04-29

Background:
    Per the role-split decision (admins do not have approval/review
    surface; managers handle approvals and reviewer inbox), a single
    human who is both an admin and a manager keeps two separate user
    accounts: one ADMIN, one MANAGER. The two accounts are linked so
    the topbar can offer a one-click "Switch to <other portal>" handoff
    without making the user re-authenticate.

This migration:
    - Adds users.linked_user_id (FK to users.id, ON DELETE SET NULL).
    - Adds an index on linked_user_id for fast reverse lookups.

Linkage semantics (enforced at the API layer, not by DB constraints):
    - Each user can be linked to at most one other user.
    - Linkage is symmetric: if A.linked_user_id = B.id then
      B.linked_user_id should be A.id. The handoff endpoint refuses
      asymmetric setups.
    - Linked accounts must belong to the same tenant.

Backwards compat: NULL by default. Existing rows are unchanged.
"""
from alembic import op
import sqlalchemy as sa


revision = "039_user_linked_account"
down_revision = "038_schema_drift_catchup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "linked_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_users_linked_user_id",
        "users",
        ["linked_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_users_linked_user_id", table_name="users")
    op.drop_constraint(
        "users_linked_user_id_fkey",
        "users",
        type_="foreignkey",
    )
    op.drop_column("users", "linked_user_id")
