"""Add client_email_domains join table

Revision ID: 035_client_email_domains
Revises: 034_chain_senders
Create Date: 2026-04-27

Backs the multi-domain client mapping used by the ingestion resolver. A
single Client (e.g. DXC Technology) can own several email domains
(dxc.com, dxctech.com, dxc-uk.com); incoming emails are matched to the
client by sender / forwarded-from / body-email domain.

Backwards compatible: clients without rows in this table fall back to the
legacy contact_email-domain heuristic in
app.services.ingestion_pipeline._client_id_for_domain.

Unique on (tenant_id, domain) prevents:
  - cross-tenant domain steal (tenant A claiming dxc.com away from
    tenant B's mapping is impossible — each tenant has its own row)
  - in-tenant duplicates of the same (client, domain) pair

Index on (tenant_id, domain) backs the resolver's reverse lookup.
"""
from alembic import op
import sqlalchemy as sa


revision = "035_client_email_domains"
down_revision = "034_chain_senders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_email_domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Stored normalized lowercased; enforced at the model layer with a
        # validates hook. No Postgres CITEXT — keep portable to SQLite.
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "domain", name="uq_client_email_domain_tenant_domain"
        ),
    )
    op.create_index(
        "ix_client_email_domains_tenant_domain",
        "client_email_domains",
        ["tenant_id", "domain"],
    )
    op.create_index(
        "ix_client_email_domains_client_id",
        "client_email_domains",
        ["client_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_client_email_domains_client_id", table_name="client_email_domains")
    op.drop_index("ix_client_email_domains_tenant_domain", table_name="client_email_domains")
    op.drop_table("client_email_domains")
