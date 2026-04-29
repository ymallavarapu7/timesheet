"""Tenant directory entry, control-plane edition.

Mirrors the legacy ``app.models.tenant.Tenant`` shape but lives in the
control-plane database. Phase 3.B+ extends this with the per-tenant
database connection details (``db_name``, encrypted credentials,
``is_isolated`` flag). Phase 3.A keeps the columns that already exist
in the shared DB so the control-plane copy is a drop-in directory.

Why a separate class instead of reusing ``Tenant``: the relationships
on the legacy model point to per-tenant tables (``users``,
``clients``, ``projects``). Those tables don't exist in the control
plane and importing them on this base would fail. Keeping the classes
separate also forces every callsite to be explicit about which DB it
expects to talk to.
"""
from __future__ import annotations

import enum
from typing import Optional

from sqlalchemy import Boolean, Enum as SAEnum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.models.control import ControlBase


class ControlTenantStatus(str, enum.Enum):
    """Mirror of the legacy ``TenantStatus`` enum.

    Kept as a separate type so the SQLAlchemy enum binding lives on
    ``ControlBase``'s metadata and never collides with the legacy
    enum's binding on the tenant DB metadata.
    """

    active = "active"
    inactive = "inactive"
    suspended = "suspended"


class ControlTenant(ControlBase, TimestampMixin):
    """Tenant directory row in the control-plane database."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    status: Mapped[ControlTenantStatus] = mapped_column(
        SAEnum(ControlTenantStatus, name="control_tenant_status"),
        default=ControlTenantStatus.active,
        nullable=False,
    )
    ingestion_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    max_mailboxes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, default=None
    )

    def __repr__(self) -> str:
        return f"<ControlTenant(id={self.id}, slug={self.slug}, status={self.status})>"
