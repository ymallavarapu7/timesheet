from sqlalchemy import String, ForeignKey, Text, Enum as SQLEnum, DateTime, Numeric, Date, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from enum import Enum
from typing import Optional
from datetime import datetime, date
from decimal import Decimal
from .base import Base, TimestampMixin


class TimeOffType(str, Enum):
    SICK_DAY = "SICK_DAY"
    PTO = "PTO"
    HALF_DAY = "HALF_DAY"
    HOURLY_PERMISSION = "HOURLY_PERMISSION"
    OTHER_LEAVE = "OTHER_LEAVE"


class TimeOffStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TimeOffRequest(Base, TimestampMixin):
    __tablename__ = "time_off_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True)
    request_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True)
    hours: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    leave_type: Mapped[TimeOffType] = mapped_column(
        SQLEnum(TimeOffType), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TimeOffStatus] = mapped_column(
        SQLEnum(TimeOffStatus), nullable=False, default=TimeOffStatus.DRAFT, index=True
    )

    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]
                             ] = mapped_column(Text, nullable=True)
    external_reference: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True)

    user: Mapped["User"] = relationship(
        "User", back_populates="time_off_requests", foreign_keys=[user_id]
    )
    approved_by_user: Mapped[Optional["User"]] = relationship(
        "User", back_populates="approved_time_off_requests", foreign_keys=[approved_by]
    )

    def __repr__(self) -> str:
        return (
            f"<TimeOffRequest(id={self.id}, user_id={self.user_id}, "
            f"request_date={self.request_date}, status={self.status})>"
        )
