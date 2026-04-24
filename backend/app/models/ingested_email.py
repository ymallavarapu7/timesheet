from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base


class IngestedEmail(Base):
    __tablename__ = "ingested_emails"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "message_id",
            name="uq_ingested_emails_tenant_message",
        ),
        Index("ix_ingested_emails_tenant_received", "tenant_id", "received_at"),
        Index("ix_ingested_emails_mailbox", "mailbox_id", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    mailbox_id: Mapped[int] = mapped_column(
        ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Populated when the incoming email was recognized as a forward and the
    # original sender was successfully extracted from the body. Otherwise
    # both are NULL and the outer sender_email/sender_name applies.
    forwarded_from_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    forwarded_from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipients: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    has_attachments: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    raw_headers: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    llm_classification: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    # list[{"name": str | None, "email": str | None}] — every distinct sender
    # pulled from the forward chain (nested RFC822 parts + body-quoted From:).
    # Stored as JSON so it reads identically across Postgres (JSONB) and the
    # SQLite test harness. NULL when the email isn't a recognizable forward
    # or is a pure reply chain. See app.services.email_parser and the
    # ingestion_pipeline chain-candidate resolution for usage.
    chain_senders: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )

    mailbox: Mapped["Mailbox"] = relationship(
        "Mailbox", back_populates="emails"
    )
    attachments: Mapped[list["EmailAttachment"]] = relationship(
        "EmailAttachment", back_populates="email",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    ingestion_timesheets: Mapped[list["IngestionTimesheet"]] = relationship(
        "IngestionTimesheet", back_populates="email",
        cascade="all, delete-orphan", passive_deletes=True,
    )
