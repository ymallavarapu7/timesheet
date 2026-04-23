import enum
from typing import Optional

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class TenantStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    suspended = "suspended"


class Tenant(Base, TimestampMixin):
    """Tenant model — one row per consulting company."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    status: Mapped[TenantStatus] = mapped_column(
        SAEnum(TenantStatus), default=TenantStatus.active, nullable=False
    )
    ingestion_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # Cap on number of mailboxes a tenant can connect. Only meaningful when
    # ingestion_enabled is True. NULL = no cap (legacy / unlimited plans).
    # Default 1 for new ingestion-enabled tenants — platform admin raises it.
    max_mailboxes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    # IANA timezone name (e.g. "America/New_York"). NULL = fall back to UTC
    # for deadline calculations and notifications. See app.core.timezone_utils.
    timezone: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, default=None
    )
    deployment_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="saas", server_default="saas"
    )
    license_expiry_behavior: Mapped[str] = mapped_column(
        String(20), nullable=False, default="read_only", server_default="read_only"
    )
    license_jti: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("issued_licenses.jti", ondelete="SET NULL"),
        nullable=True,
    )
    license_grace_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Back-populated from each tenant-scoped model
    users: Mapped[list["User"]] = relationship("User", back_populates="tenant")
    clients: Mapped[list["Client"]] = relationship("Client", back_populates="tenant")
    projects: Mapped[list["Project"]] = relationship("Project", back_populates="tenant")

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, slug={self.slug}, status={self.status})>"
