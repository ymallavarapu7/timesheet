from typing import List, Optional

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_roles_tenant_id_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )

    tenant: Mapped[Optional["Tenant"]] = relationship("Tenant")
    role_permissions: Mapped[List["RolePermission"]] = relationship(
        "RolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
    )
    role_assignments: Mapped[List["RoleAssignment"]] = relationship(
        "RoleAssignment",
        back_populates="role",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Role(id={self.id}, code={self.code!r}, tenant_id={self.tenant_id})>"


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("permissions.code", ondelete="CASCADE"),
        primary_key=True,
    )

    role: Mapped["Role"] = relationship("Role", back_populates="role_permissions")
    permission: Mapped["Permission"] = relationship(
        "Permission",
        back_populates="role_permissions",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<RolePermission(role_id={self.role_id}, "
            f"permission_code={self.permission_code!r})>"
        )
