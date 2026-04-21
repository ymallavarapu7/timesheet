from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "role_id",
            "effective_from",
            name="uq_role_assignments_user_role_from",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="tenant",
        server_default="tenant",
    )
    scope_ref_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        server_default=func.current_date(),
    )
    effective_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )
    granted_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    role: Mapped["Role"] = relationship("Role", back_populates="role_assignments")
    granted_by_user: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[granted_by],
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<RoleAssignment(id={self.id}, user_id={self.user_id}, "
            f"role_id={self.role_id}, scope_type={self.scope_type!r})>"
        )
