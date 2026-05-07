"""role revamp: remove SENIOR_MANAGER, rename CEO to VIEWER

Revision ID: 046
Revises: 045
Create Date: 2026-05-07
"""
from alembic import op
import sqlalchemy as sa

revision = "046_role_revamp"
down_revision = "045_mailbox_needs_reauth"
branch_labels = None
depends_on = None

NEW_VALUES = ("EMPLOYEE", "MANAGER", "VIEWER", "ADMIN", "PLATFORM_ADMIN")
OLD_VALUES = ("EMPLOYEE", "MANAGER", "SENIOR_MANAGER", "CEO", "ADMIN", "PLATFORM_ADMIN")


def upgrade() -> None:
    # Step 1: detach the column from the enum so we can freely update text values
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE text USING role::text")

    # Step 2: migrate the text values
    op.execute("UPDATE users SET role = 'MANAGER' WHERE role = 'SENIOR_MANAGER'")
    op.execute("UPDATE users SET role = 'VIEWER' WHERE role = 'CEO'")

    # Step 3: migrate JSONB roles array
    op.execute("""
        UPDATE users
        SET roles = (
            SELECT jsonb_agg(
                CASE
                    WHEN r = 'SENIOR_MANAGER' THEN 'MANAGER'
                    WHEN r = 'CEO' THEN 'VIEWER'
                    ELSE r
                END
            )
            FROM jsonb_array_elements_text(roles) AS r
        )
        WHERE roles IS NOT NULL AND roles != '[]'::jsonb
          AND (roles::text LIKE '%SENIOR_MANAGER%' OR roles::text LIKE '%CEO%')
    """)

    # Step 4: drop default (depends on enum type), drop old enum, create new one
    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
    op.execute("DROP TYPE userrole")
    op.execute(f"CREATE TYPE userrole AS ENUM {NEW_VALUES}")

    # Step 5: reattach column to new enum and restore default
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::userrole")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'EMPLOYEE'::userrole")


def downgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE text USING role::text")
    op.execute("UPDATE users SET role = 'CEO' WHERE role = 'VIEWER'")
    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
    op.execute("DROP TYPE userrole")
    op.execute(f"CREATE TYPE userrole AS ENUM {OLD_VALUES}")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::userrole")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'EMPLOYEE'::userrole")
