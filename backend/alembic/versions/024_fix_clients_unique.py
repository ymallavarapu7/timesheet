"""Ensure clients unique constraint is (tenant_id, name), not (name) alone

Revision ID: 024_fix_clients_unique
Revises: 023_max_mailboxes
Create Date: 2026-04-17

Local dev already has `uq_client_tenant_name` from model metadata; prod may
still have the legacy single-column `clients_name_key` constraint which blocks
two tenants from having clients with the same name. IF EXISTS / IF NOT EXISTS
makes this safe on both.
"""
from alembic import op

revision = "024_fix_clients_unique"
down_revision = "023_max_mailboxes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the legacy single-column unique constraint if it's still there.
    op.execute("ALTER TABLE clients DROP CONSTRAINT IF EXISTS clients_name_key;")
    # Create the composite (tenant_id, name) constraint if it isn't already.
    # DO $$ block because Postgres has no native IF NOT EXISTS for constraints.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_client_tenant_name'
                AND conrelid = 'clients'::regclass
            ) THEN
                ALTER TABLE clients
                ADD CONSTRAINT uq_client_tenant_name UNIQUE (tenant_id, name);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE clients DROP CONSTRAINT IF EXISTS uq_client_tenant_name;")
    # Re-adding the old single-column constraint would fail if multiple tenants
    # have same-named clients — leave it up to the caller to recreate manually.
