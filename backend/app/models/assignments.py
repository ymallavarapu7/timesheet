from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class EmployeeManagerAssignment(Base, TimestampMixin):
    __tablename__ = "employee_manager_assignments"

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), primary_key=True)
    manager_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True)

    employee = relationship(
        "User",
        foreign_keys=[employee_id],
        back_populates="manager_assignment",
    )
    manager = relationship(
        "User",
        foreign_keys=[manager_id],
        back_populates="direct_report_assignments",
    )


class UserProjectAccess(Base, TimestampMixin):
    __tablename__ = "user_project_access"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), primary_key=True)

    user = relationship("User", back_populates="project_access")
    project = relationship("Project", back_populates="user_access")
