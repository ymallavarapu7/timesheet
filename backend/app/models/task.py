from typing import List, Optional

from sqlalchemy import Boolean, ForeignKey, String, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True)

    project: Mapped["Project"] = relationship(
        "Project", back_populates="tasks")
    time_entries: Mapped[List["TimeEntry"]] = relationship(
        "TimeEntry", back_populates="task")

    def __repr__(self) -> str:
        return (
            f"<Task(id={self.id}, project_id={self.project_id}, "
            f"name={self.name}, is_active={self.is_active})>"
        )
