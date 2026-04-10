"""Add Microsoft Graph mailbox protocol.

Revision ID: 008_add_graph_mailbox_protocol
Revises: 007_add_ingestion_tables
Create Date: 2026-03-31
"""

from typing import Sequence, Union

from alembic import op

revision: str = "008_add_graph_mailbox_protocol"
down_revision: Union[str, None] = "007_add_ingestion_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            ALTER TYPE mailboxprotocol ADD VALUE IF NOT EXISTS 'graph';
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE mailboxes
        SET protocol = 'imap'
        WHERE protocol::text = 'graph';
        """
    )
    op.execute("ALTER TYPE mailboxprotocol RENAME TO mailboxprotocol_old;")
    op.execute("CREATE TYPE mailboxprotocol AS ENUM ('imap', 'pop3');")
    op.execute(
        """
        ALTER TABLE mailboxes
        ALTER COLUMN protocol TYPE mailboxprotocol
        USING protocol::text::mailboxprotocol;
        """
    )
    op.execute("DROP TYPE mailboxprotocol_old;")
