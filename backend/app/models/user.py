from sqlalchemy import String, Boolean, Integer, Enum as SQLEnum, ForeignKey, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from enum import Enum
from typing import Optional, List
from datetime import datetime
from .base import Base, TimestampMixin


class UserRole(str, Enum):
    """User role enumeration."""
    EMPLOYEE = "EMPLOYEE"
    MANAGER = "MANAGER"
    SENIOR_MANAGER = "SENIOR_MANAGER"
    CEO = "CEO"
    ADMIN = "ADMIN"           # Tenant-scoped admin
    PLATFORM_ADMIN = "PLATFORM_ADMIN"  # Global admin — no tenant_id


class User(Base, TimestampMixin):
    """User model for authentication and role-based access."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, default="UTC")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    has_changed_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False)
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole), nullable=False, default=UserRole.EMPLOYEE)
    # The set of roles this user is allowed to act as. The active role
    # (the one require_role checks against, the one that lands in the
    # JWT) lives in the `role` column above; `roles` is the menu of
    # allowed values that can be flipped to via /auth/switch-role.
    # For single-role users it is always [role]. For a user who is both
    # an admin and a manager it is ["ADMIN", "MANAGER"].
    roles: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True)
    can_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_external: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    timesheet_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    timesheet_locked_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Account lockout
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Email verification
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    email_verification_token: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )
    email_verification_token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Ingestion platform cross-reference
    ingestion_employee_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, unique=True, index=True
    )
    ingestion_created_by: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # Optional pinning — if set, ingestion auto-assigns this client on any
    # timesheet resolved to this user without needing to match client signals.
    default_client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Legacy column from the dual-account portal-handoff model. Kept
    # in the schema (the DB drop is a follow-up migration) but no
    # application code reads it; the multi-role refactor replaced
    # account linkage with the users.roles array.
    linked_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Relationships
    tenant: Mapped[Optional["Tenant"]] = relationship("Tenant", back_populates="users")
    manager_assignment: Mapped[Optional["EmployeeManagerAssignment"]] = relationship(
        "EmployeeManagerAssignment",
        back_populates="employee",
        foreign_keys="EmployeeManagerAssignment.employee_id",
        cascade="all, delete-orphan",
        uselist=False,
    )
    direct_report_assignments: Mapped[List["EmployeeManagerAssignment"]] = relationship(
        "EmployeeManagerAssignment",
        back_populates="manager",
        foreign_keys="EmployeeManagerAssignment.manager_id",
    )
    project_access: Mapped[List["UserProjectAccess"]] = relationship(
        "UserProjectAccess",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    time_entries: Mapped[List["TimeEntry"]] = relationship(
        "TimeEntry", back_populates="user", foreign_keys="TimeEntry.user_id")
    approved_entries: Mapped[List["TimeEntry"]] = relationship(
        "TimeEntry", back_populates="approved_by_user", foreign_keys="TimeEntry.approved_by")
    time_off_requests: Mapped[List["TimeOffRequest"]] = relationship(
        "TimeOffRequest", back_populates="user", foreign_keys="TimeOffRequest.user_id")
    approved_time_off_requests: Mapped[List["TimeOffRequest"]] = relationship(
        "TimeOffRequest", back_populates="approved_by_user", foreign_keys="TimeOffRequest.approved_by")

    @property
    def manager_id(self) -> Optional[int]:
        return self.manager_assignment.manager_id if self.manager_assignment else None

    @property
    def project_ids(self) -> List[int]:
        return sorted(access.project_id for access in self.project_access)

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role}, is_active={self.is_active})>"
