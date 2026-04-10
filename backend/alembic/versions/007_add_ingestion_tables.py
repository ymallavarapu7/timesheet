"""Add email ingestion tables and enum types.

Revision ID: 007_add_ingestion_tables
Revises: 006_add_user_flags
Create Date: 2026-03-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007_add_ingestion_tables"
down_revision: Union[str, None] = "006_add_user_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(
        index["name"] == index_name
        for index in _inspector().get_indexes(table_name)
    )


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE mailboxprotocol AS ENUM ('imap', 'pop3');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE mailboxauthtype AS ENUM ('basic', 'oauth2');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE oauthprovider AS ENUM ('google', 'microsoft');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE extractionmethod AS ENUM (
                'native_pdf',
                'native_spreadsheet',
                'tesseract',
                'vision_api',
                'llm_structured'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE extractionstatus AS ENUM (
                'pending',
                'processing',
                'completed',
                'failed'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE sendermatchtype AS ENUM ('email', 'domain');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE ingestiontimesheetstatus AS ENUM (
                'pending',
                'under_review',
                'approved',
                'rejected',
                'on_hold'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE ingestionactortype AS ENUM ('user', 'system');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    mailbox_protocol = postgresql.ENUM(
        "imap", "pop3", name="mailboxprotocol", create_type=False
    )
    mailbox_auth_type = postgresql.ENUM(
        "basic", "oauth2", name="mailboxauthtype", create_type=False
    )
    oauth_provider = postgresql.ENUM(
        "google", "microsoft", name="oauthprovider", create_type=False
    )
    extraction_method = postgresql.ENUM(
        "native_pdf",
        "native_spreadsheet",
        "tesseract",
        "vision_api",
        "llm_structured",
        name="extractionmethod",
        create_type=False,
    )
    extraction_status = postgresql.ENUM(
        "pending",
        "processing",
        "completed",
        "failed",
        name="extractionstatus",
        create_type=False,
    )
    sender_match_type = postgresql.ENUM(
        "email", "domain", name="sendermatchtype", create_type=False
    )
    ingestion_timesheet_status = postgresql.ENUM(
        "pending",
        "under_review",
        "approved",
        "rejected",
        "on_hold",
        name="ingestiontimesheetstatus",
        create_type=False,
    )
    ingestion_actor_type = postgresql.ENUM(
        "user", "system", name="ingestionactortype", create_type=False
    )

    if not _table_exists("mailboxes"):
        op.create_table(
            "mailboxes",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=False),
            sa.Column("protocol", mailbox_protocol, nullable=False),
            sa.Column("host", sa.String(length=255), nullable=True),
            sa.Column("port", sa.Integer(), nullable=True),
            sa.Column("use_ssl", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column(
                "auth_type",
                mailbox_auth_type,
                nullable=False,
                server_default="basic",
            ),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column("password_enc", sa.String(length=512), nullable=True),
            sa.Column("oauth_provider", oauth_provider, nullable=True),
            sa.Column("oauth_email", sa.String(length=255), nullable=True),
            sa.Column("oauth_access_token_enc", sa.String(length=2048), nullable=True),
            sa.Column("oauth_refresh_token_enc", sa.String(length=2048), nullable=True),
            sa.Column("oauth_token_expiry", sa.DateTime(timezone=True), nullable=True),
            sa.Column("smtp_host", sa.String(length=255), nullable=True),
            sa.Column("smtp_port", sa.Integer(), nullable=True),
            sa.Column("smtp_username", sa.String(length=255), nullable=True),
            sa.Column("smtp_password_enc", sa.String(length=512), nullable=True),
            sa.Column("linked_client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_mailboxes_tenant_id", "mailboxes", ["tenant_id"])
    _create_index_if_missing("ix_mailboxes_tenant_active", "mailboxes", ["tenant_id", "is_active"])

    if not _table_exists("email_sender_mappings"):
        op.create_table(
            "email_sender_mappings",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("match_type", sender_match_type, nullable=False),
            sa.Column("match_value", sa.String(length=255), nullable=False),
            sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(
        "ix_email_sender_mappings_tenant_id",
        "email_sender_mappings",
        ["tenant_id"],
    )
    _create_index_if_missing(
        "ix_email_sender_mappings_lookup",
        "email_sender_mappings",
        ["tenant_id", "match_value"],
    )

    if not _table_exists("ingested_emails"):
        op.create_table(
            "ingested_emails",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("mailbox_id", sa.Integer(), sa.ForeignKey("mailboxes.id"), nullable=False),
            sa.Column("message_id", sa.String(length=512), nullable=False),
            sa.Column("subject", sa.String(length=1024), nullable=True),
            sa.Column("sender_email", sa.String(length=255), nullable=False),
            sa.Column("sender_name", sa.String(length=255), nullable=True),
            sa.Column("recipients", sa.JSON(), nullable=True),
            sa.Column("body_text", sa.Text(), nullable=True),
            sa.Column("body_html", sa.Text(), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "fetched_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("has_attachments", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("raw_headers", sa.JSON(), nullable=True),
            sa.Column("llm_classification", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "message_id",
                name="uq_ingested_emails_tenant_message",
            ),
        )
    _create_index_if_missing("ix_ingested_emails_tenant_id", "ingested_emails", ["tenant_id"])
    _create_index_if_missing(
        "ix_ingested_emails_tenant_received",
        "ingested_emails",
        ["tenant_id", "received_at"],
    )
    _create_index_if_missing(
        "ix_ingested_emails_mailbox",
        "ingested_emails",
        ["mailbox_id", "fetched_at"],
    )

    if not _table_exists("email_attachments"):
        op.create_table(
            "email_attachments",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("email_id", sa.Integer(), sa.ForeignKey("ingested_emails.id"), nullable=False),
            sa.Column("filename", sa.String(length=512), nullable=False),
            sa.Column("mime_type", sa.String(length=255), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=True),
            sa.Column("storage_key", sa.String(length=1024), nullable=False),
            sa.Column("is_timesheet", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("extraction_method", extraction_method, nullable=True),
            sa.Column(
                "extraction_status",
                extraction_status,
                nullable=False,
                server_default="pending",
            ),
            sa.Column("extraction_error", sa.Text(), nullable=True),
            sa.Column("raw_extracted_text", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_email_attachments_email_id", "email_attachments", ["email_id"])
    _create_index_if_missing("ix_email_attachments_is_timesheet", "email_attachments", ["is_timesheet"])

    if not _table_exists("ingestion_timesheets"):
        op.create_table(
            "ingestion_timesheets",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("email_id", sa.Integer(), sa.ForeignKey("ingested_emails.id"), nullable=False),
            sa.Column("attachment_id", sa.Integer(), sa.ForeignKey("email_attachments.id"), nullable=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
            sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("period_start", sa.Date(), nullable=True),
            sa.Column("period_end", sa.Date(), nullable=True),
            sa.Column("total_hours", sa.Numeric(8, 2), nullable=True),
            sa.Column(
                "status",
                ingestion_timesheet_status,
                nullable=False,
                server_default="pending",
            ),
            sa.Column("extracted_data", sa.JSON(), nullable=True),
            sa.Column("corrected_data", sa.JSON(), nullable=True),
            sa.Column("llm_anomalies", sa.JSON(), nullable=True),
            sa.Column("llm_match_suggestions", sa.JSON(), nullable=True),
            sa.Column("llm_summary", sa.Text(), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("internal_notes", sa.Text(), nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "time_entries_created",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_ingestion_timesheets_tenant_id", "ingestion_timesheets", ["tenant_id"])
    _create_index_if_missing(
        "ix_ingestion_timesheets_tenant_status",
        "ingestion_timesheets",
        ["tenant_id", "status"],
    )
    _create_index_if_missing(
        "ix_ingestion_timesheets_employee",
        "ingestion_timesheets",
        ["employee_id", "period_start"],
    )
    _create_index_if_missing(
        "ix_ingestion_timesheets_reviewer",
        "ingestion_timesheets",
        ["reviewer_id", "status"],
    )

    if not _table_exists("ingestion_timesheet_line_items"):
        op.create_table(
            "ingestion_timesheet_line_items",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "ingestion_timesheet_id",
                sa.Integer(),
                sa.ForeignKey("ingestion_timesheets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("work_date", sa.Date(), nullable=False),
            sa.Column("hours", sa.Numeric(5, 2), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("project_code", sa.String(length=80), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
            sa.Column("is_corrected", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("original_value", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(
        "ix_ingestion_line_items_timesheet",
        "ingestion_timesheet_line_items",
        ["ingestion_timesheet_id"],
    )

    if not _table_exists("ingestion_audit_log"):
        op.create_table(
            "ingestion_audit_log",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "ingestion_timesheet_id",
                sa.Integer(),
                sa.ForeignKey("ingestion_timesheets.id"),
                nullable=False,
            ),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("action", sa.String(length=100), nullable=False),
            sa.Column(
                "actor_type",
                ingestion_actor_type,
                nullable=False,
                server_default="user",
            ),
            sa.Column("previous_value", sa.JSON(), nullable=True),
            sa.Column("new_value", sa.JSON(), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(
        "ix_ingestion_audit_log_timesheet",
        "ingestion_audit_log",
        ["ingestion_timesheet_id"],
    )
    _create_index_if_missing(
        "ix_ingestion_audit_log_user",
        "ingestion_audit_log",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("ingestion_audit_log")
    op.drop_table("ingestion_timesheet_line_items")
    op.drop_table("ingestion_timesheets")
    op.drop_table("email_attachments")
    op.drop_table("ingested_emails")
    op.drop_table("email_sender_mappings")
    op.drop_table("mailboxes")

    op.execute("DROP TYPE IF EXISTS ingestionactortype")
    op.execute("DROP TYPE IF EXISTS ingestiontimesheetstatus")
    op.execute("DROP TYPE IF EXISTS sendermatchtype")
    op.execute("DROP TYPE IF EXISTS extractionstatus")
    op.execute("DROP TYPE IF EXISTS extractionmethod")
    op.execute("DROP TYPE IF EXISTS oauthprovider")
    op.execute("DROP TYPE IF EXISTS mailboxauthtype")
    op.execute("DROP TYPE IF EXISTS mailboxprotocol")
