from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from .base import Base, TimestampMixin


class Client(Base, TimestampMixin):
    """Client model for representing consulting clients."""

    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_client_tenant_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quickbooks_customer_id: Mapped[Optional[str]
                                   ] = mapped_column(String(255), nullable=True)
    ingestion_client_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, unique=True, index=True
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="clients")
    projects: Mapped[List["Project"]] = relationship(
        "Project", back_populates="client", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Client(id={self.id}, name={self.name})>"
