from datetime import date

from sqlalchemy import String, Boolean, ForeignKey, Numeric, Date, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from decimal import Decimal
from .base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    """Project model for time tracking by project."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id"), nullable=False, index=True)
    billable_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False)
    quickbooks_project_id: Mapped[Optional[str]
                                  ] = mapped_column(String(255), nullable=True)
    ingestion_project_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, unique=True, index=True
    )
    code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    estimated_hours: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True)
    budget_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="projects")
    client: Mapped["Client"] = relationship(
        "Client", back_populates="projects")
    user_access: Mapped[List["UserProjectAccess"]] = relationship(
        "UserProjectAccess",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    time_entries: Mapped[List["TimeEntry"]] = relationship(
        "TimeEntry", back_populates="project", cascade="all, delete-orphan")
    tasks: Mapped[List["Task"]] = relationship(
        "Task", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name}, client_id={self.client_id}, is_active={self.is_active})>"
