from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from .base import Base, TimestampMixin


class TenantSettings(Base, TimestampMixin):
    """Key-value settings per tenant."""

    __tablename__ = "tenant_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    tenant: Mapped["Tenant"] = relationship("Tenant")

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint("tenant_id", "key", name="uq_tenant_settings_tenant_key"),
    )
