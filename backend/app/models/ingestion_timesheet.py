from datetime import date, datetime
from decimal import Decimal
import enum
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, ForeignKey, Index, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base, TimestampMixin


class IngestionTimesheetStatus(str, enum.Enum):
    pending = "pending"
    under_review = "under_review"
    approved = "approved"
    rejected = "rejected"
    on_hold = "on_hold"


class IngestionTimesheet(Base, TimestampMixin):
    __tablename__ = "ingestion_timesheets"
    __table_args__ = (
        Index("ix_ingestion_timesheets_tenant_status", "tenant_id", "status"),
        Index("ix_ingestion_timesheets_employee", "employee_id", "period_start"),
        Index("ix_ingestion_timesheets_reviewer", "reviewer_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    email_id: Mapped[int] = mapped_column(
        ForeignKey("ingested_emails.id", ondelete="CASCADE"), nullable=False
    )
    attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_attachments.id", ondelete="CASCADE"), nullable=True
    )
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    reviewer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    status: Mapped[IngestionTimesheetStatus] = mapped_column(
        SAEnum(IngestionTimesheetStatus, name="ingestiontimesheetstatus"),
        default=IngestionTimesheetStatus.pending,
        nullable=False,
    )
    extracted_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    corrected_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    llm_anomalies: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    llm_match_suggestions: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    llm_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_supervisor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Reviewer-confirmed supervisor. Pre-filled at ingestion time when the
    # extracted_supervisor_name fuzzy-matches an existing tenant user; the
    # reviewer can override on the review page. Carried forward to every
    # TimeEntry created on approval (see api/ingestion.py::approve_timesheet).
    supervisor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    time_entries_created: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    email: Mapped["IngestedEmail"] = relationship(
        "IngestedEmail", back_populates="ingestion_timesheets"
    )
    attachment: Mapped["EmailAttachment | None"] = relationship(
        "EmailAttachment", back_populates="ingestion_timesheets"
    )
    employee: Mapped["User | None"] = relationship(
        "User", foreign_keys=[employee_id]
    )
    reviewer: Mapped["User | None"] = relationship(
        "User", foreign_keys=[reviewer_id]
    )
    supervisor: Mapped["User | None"] = relationship(
        "User", foreign_keys=[supervisor_user_id]
    )
    client: Mapped["Client | None"] = relationship("Client")
    line_items: Mapped[list["IngestionTimesheetLineItem"]] = relationship(
        "IngestionTimesheetLineItem",
        back_populates="ingestion_timesheet",
        cascade="all, delete-orphan",
    )
    audit_log: Mapped[list["IngestionAuditLog"]] = relationship(
        "IngestionAuditLog", back_populates="ingestion_timesheet",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class IngestionTimesheetLineItem(Base):
    __tablename__ = "ingestion_timesheet_line_items"
    __table_args__ = (
        Index("ix_ingestion_line_items_timesheet", "ingestion_timesheet_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ingestion_timesheet_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_timesheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    is_corrected: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    original_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_rejected: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    ingestion_timesheet: Mapped["IngestionTimesheet"] = relationship(
        "IngestionTimesheet", back_populates="line_items"
    )
    project: Mapped["Project | None"] = relationship("Project")


class IngestionAuditActorType(str, enum.Enum):
    user = "user"
    system = "system"


class IngestionAuditLog(Base):
    __tablename__ = "ingestion_audit_log"
    __table_args__ = (
        Index("ix_ingestion_audit_log_timesheet", "ingestion_timesheet_id"),
        Index("ix_ingestion_audit_log_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ingestion_timesheet_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_timesheets.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[IngestionAuditActorType] = mapped_column(
        SAEnum(IngestionAuditActorType, name="ingestionactortype"),
        default=IngestionAuditActorType.user,
        nullable=False,
    )
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ingestion_timesheet: Mapped["IngestionTimesheet"] = relationship(
        "IngestionTimesheet", back_populates="audit_log"
    )
    user: Mapped["User | None"] = relationship("User")
