from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from .base import Base, TimestampMixin


class PlatformSettings(Base, TimestampMixin):
    """Key-value settings for the platform (not tenant-scoped)."""

    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
