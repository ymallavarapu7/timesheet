from sqlalchemy import Boolean, String, ForeignKey, Text, Enum as SQLEnum, DateTime, Numeric, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from enum import Enum
from typing import Optional, TYPE_CHECKING
from datetime import date, datetime
from decimal import Decimal
from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .project import Project
    from .task import Task
    from .user import User


class TimeEntryStatus(str, Enum):
    """Status enumeration for time entries."""
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TimeEntry(Base, TimestampMixin):
    """TimeEntry model for tracking billable hours."""

    __tablename__ = "time_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True)
    task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tasks.id"), nullable=True, index=True)
    entry_date: Mapped[date] = mapped_column(nullable=False, index=True)
    hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False)  # 0.00 to 999.99
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_billable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True)
    status: Mapped[TimeEntryStatus] = mapped_column(SQLEnum(
        TimeEntryStatus), nullable=False, default=TimeEntryStatus.DRAFT, index=True)

    # Approval tracking
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]
                             ] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    last_edit_reason: Mapped[Optional[str]
                             ] = mapped_column(Text, nullable=True)
    last_history_summary: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True)

    # QuickBooks integration (future)
    quickbooks_time_activity_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True)

    # Ingestion platform cross-reference
    ingestion_timesheet_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )
    ingestion_line_item_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, unique=True, index=True
    )
    ingestion_approved_by_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    ingestion_source_tenant: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User", back_populates="time_entries", foreign_keys=[user_id])
    project: Mapped["Project"] = relationship(
        "Project", back_populates="time_entries")
    task: Mapped[Optional["Task"]] = relationship(
        "Task", back_populates="time_entries")
    approved_by_user: Mapped[Optional["User"]] = relationship(
        "User", back_populates="approved_entries", foreign_keys=[approved_by])
    edit_history: Mapped[list["TimeEntryEditHistory"]] = relationship(
        "TimeEntryEditHistory",
        back_populates="time_entry",
        cascade="all, delete-orphan",
    )

    @property
    def approved_by_name(self) -> Optional[str]:
        """Convenience for response serialization. Requires approved_by_user to be eager-loaded."""
        try:
            return self.approved_by_user.full_name if self.approved_by_user else None
        except Exception:
            return None

    def __repr__(self) -> str:
        return f"<TimeEntry(id={self.id}, user_id={self.user_id}, project_id={self.project_id}, date={self.entry_date}, status={self.status})>"


class TimeEntryEditHistory(Base):
    __tablename__ = "time_entry_edit_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    time_entry_id: Mapped[int] = mapped_column(
        ForeignKey("time_entries.id"), nullable=False, index=True)
    edited_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True)
    edited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)
    edit_reason: Mapped[str] = mapped_column(Text, nullable=False)
    history_summary: Mapped[str] = mapped_column(Text, nullable=False)
    previous_project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False)
    previous_entry_date: Mapped[date] = mapped_column(nullable=False)
    previous_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False)
    previous_description: Mapped[str] = mapped_column(Text, nullable=False)

    time_entry: Mapped["TimeEntry"] = relationship(
        "TimeEntry", back_populates="edit_history")
