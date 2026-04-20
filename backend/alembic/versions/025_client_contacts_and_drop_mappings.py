"""Add client contact fields + user.default_client_id; drop email_sender_mappings

Revision ID: 025_client_contacts
Revises: 024_fix_clients_unique
Create Date: 2026-04-20

Collapses the mappings table into structures that already exist:
- Per-employee client pinning moves onto users.default_client_id.
- Domain-based routing becomes a derived signal from the client's contact_email.
The email_sender_mappings table and its enum are dropped; it was unused in
production and the signals it carried are now represented on Client/User.
"""
from alembic import op
import sqlalchemy as sa

revision = "025_client_contacts"
down_revision = "024_fix_clients_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── clients: contact fields ────────────────────────────────────────────
    op.add_column("clients", sa.Column("contact_name", sa.String(length=255), nullable=True))
    op.add_column("clients", sa.Column("contact_email", sa.String(length=255), nullable=True))
    op.add_column("clients", sa.Column("contact_phone", sa.String(length=64), nullable=True))
    # Index the domain part of contact_email for fast sender-domain lookups.
    # Postgres functional index using SPLIT_PART.
    op.execute(
        """
        CREATE INDEX ix_clients_contact_email_domain
        ON clients (tenant_id, LOWER(SPLIT_PART(contact_email, '@', 2)))
        WHERE contact_email IS NOT NULL;
        """
    )

    # ── users: default_client_id ───────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "default_client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_users_default_client_id", "users", ["default_client_id"])

    # ── drop email_sender_mappings + enum ──────────────────────────────────
    op.execute("DROP TABLE IF EXISTS email_sender_mappings CASCADE;")
    op.execute("DROP TYPE IF EXISTS sendermatchtype;")


def downgrade() -> None:
    # Recreate the mappings table (no data restored — this was a destructive drop).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sendermatchtype') THEN
                CREATE TYPE sendermatchtype AS ENUM ('email', 'domain');
            END IF;
        END $$;
        """
    )
    op.create_table(
        "email_sender_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("match_type", sa.Enum("email", "domain", name="sendermatchtype", create_type=False), nullable=False),
        sa.Column("match_value", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_email_sender_mappings_lookup", "email_sender_mappings", ["tenant_id", "match_value"])

    op.drop_index("ix_users_default_client_id", table_name="users")
    op.drop_column("users", "default_client_id")

    op.execute("DROP INDEX IF EXISTS ix_clients_contact_email_domain;")
    op.drop_column("clients", "contact_phone")
    op.drop_column("clients", "contact_email")
    op.drop_column("clients", "contact_name")
