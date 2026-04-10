"""Set activity_log.actor_user_id FK to ON DELETE SET NULL.

Revision ID: 014_activity_log_fk_set_null
Revises: 013_add_email_verification
Create Date: 2026-04-07
"""

from alembic import op

revision = "014_activity_log_fk_set_null"
down_revision = "013_add_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("activity_log_actor_user_id_fkey", "activity_log", type_="foreignkey")
    op.create_foreign_key(
        "activity_log_actor_user_id_fkey",
        "activity_log", "users",
        ["actor_user_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("activity_log_actor_user_id_fkey", "activity_log", type_="foreignkey")
    op.create_foreign_key(
        "activity_log_actor_user_id_fkey",
        "activity_log", "users",
        ["actor_user_id"], ["id"],
    )
