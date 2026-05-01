"""Tenant directory entry, control-plane edition.

Separate class from the legacy ``Tenant`` because that one's
relationships point at per-tenant tables that don't exist here.
"""
from __future__ import annotations

import enum
from typing import Optional

from sqlalchemy import Boolean, Enum as SAEnum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.models.control import ControlBase


class ControlTenantStatus(str, enum.Enum):
    """Mirror of the legacy TenantStatus enum, bound to ControlBase metadata."""

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

    # Per-tenant DB connection details. ``is_isolated`` is the cutover flag.
    db_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    db_host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    db_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Credentials encrypted with the OAuth-token AES-256-GCM key.
    db_user_enc: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    db_password_enc: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_isolated: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    def __repr__(self) -> str:
        return f"<ControlTenant(id={self.id}, slug={self.slug}, status={self.status})>"
