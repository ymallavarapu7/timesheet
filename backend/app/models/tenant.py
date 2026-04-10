import enum

from sqlalchemy import Boolean, Enum as SAEnum, String
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

    # Back-populated from each tenant-scoped model
    users: Mapped[list["User"]] = relationship("User", back_populates="tenant")
    clients: Mapped[list["Client"]] = relationship("Client", back_populates="tenant")
    projects: Mapped[list["Project"]] = relationship("Project", back_populates="tenant")

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, slug={self.slug}, status={self.status})>"
