from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from .base import Base


class IssuedLicense(Base):
    __tablename__ = "issued_licenses"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    server_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tier: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="enterprise",
        server_default="enterprise",
    )
    max_users: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    features: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    issued_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoke_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_verified: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_active_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
