from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from .base import Base


class ClientEmailDomain(Base):
    """
    Maps an email domain to a Client for the ingestion resolver.

    A client may own multiple domains (e.g. DXC owns dxc.com, dxctech.com).
    Domain is stored normalized (lowercased, stripped) so lookups can be
    direct equality with no per-row casefold.
    """

    __tablename__ = "client_email_domains"
    __table_args__ = (
        UniqueConstraint("tenant_id", "domain", name="uq_client_email_domain_tenant_domain"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    client: Mapped["Client"] = relationship("Client", back_populates="email_domains")

    @validates("domain")
    def _normalize_domain(self, _key: str, value: Optional[str]) -> str:
        if value is None:
            raise ValueError("domain is required")
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("domain cannot be blank")
        if "@" in normalized:
            raise ValueError(
                "domain must not contain '@' — pass the bare domain (e.g. 'dxc.com')"
            )
        return normalized

    def __repr__(self) -> str:
        return f"<ClientEmailDomain(client_id={self.client_id}, domain={self.domain!r})>"
