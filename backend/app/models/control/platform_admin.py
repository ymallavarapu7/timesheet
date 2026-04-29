"""Platform-admin user accounts, control-plane edition.

PLATFORM_ADMIN logins live here, not in any tenant's ``users`` table.
Tenant users continue to live in the per-tenant ``users`` table; the
two are intentionally separate auth surfaces.

This is its own table rather than a flag on a shared ``users`` table
because:

1. Tenant users are scoped to one tenant DB once 3.B/3.C lands. A
   platform admin spans tenants and cannot live inside any one tenant
   DB.
2. The legacy ``users`` table holds tenant-only columns (manager_id,
   is_billable, etc.) that don't apply to platform admins. Forcing
   them onto the same row created NULL columns and special cases.
"""
from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.models.control import ControlBase


class PlatformAdmin(ControlBase, TimestampMixin):
    """A platform-admin account.

    Authenticates against the control-plane database. Has no
    ``tenant_id`` because the role is intentionally cross-tenant.
    """

    __tablename__ = "platform_admins"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    username: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    has_changed_password: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    def __repr__(self) -> str:
        return f"<PlatformAdmin(id={self.id}, email={self.email})>"
