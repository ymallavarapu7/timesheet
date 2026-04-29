"""Platform-wide key/value settings, control-plane edition.

Mirrors ``app.models.platform_settings.PlatformSettings`` but bound to
the control-plane base. Tenant settings continue to live in the tenant
DB as ``tenant_settings``.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.models.control import ControlBase


class ControlPlatformSettings(ControlBase, TimestampMixin):
    """Single key/value row used for platform-wide configuration."""

    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
