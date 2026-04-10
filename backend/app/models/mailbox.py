from datetime import datetime
import enum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class MailboxProtocol(str, enum.Enum):
    imap = "imap"
    pop3 = "pop3"
    graph = "graph"


class MailboxAuthType(str, enum.Enum):
    basic = "basic"
    oauth2 = "oauth2"


class OAuthProvider(str, enum.Enum):
    google = "google"
    microsoft = "microsoft"


class Mailbox(Base, TimestampMixin):
    __tablename__ = "mailboxes"
    __table_args__ = (
        Index("ix_mailboxes_tenant_active", "tenant_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    protocol: Mapped[MailboxProtocol] = mapped_column(
        SAEnum(MailboxProtocol, name="mailboxprotocol"), nullable=False
    )

    # Basic auth
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auth_type: Mapped[MailboxAuthType] = mapped_column(
        SAEnum(MailboxAuthType, name="mailboxauthtype"),
        default=MailboxAuthType.basic,
        nullable=False,
    )
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # OAuth2
    oauth_provider: Mapped[OAuthProvider | None] = mapped_column(
        SAEnum(OAuthProvider, name="oauthprovider"), nullable=True
    )
    oauth_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oauth_access_token_enc: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    oauth_refresh_token_enc: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    oauth_token_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # SMTP (future)
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_password_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)

    linked_client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped["Tenant"] = relationship("Tenant")
    linked_client: Mapped["Client | None"] = relationship("Client")
    emails: Mapped[list["IngestedEmail"]] = relationship(
        "IngestedEmail", back_populates="mailbox",
        cascade="all, delete-orphan", passive_deletes=True,
    )
