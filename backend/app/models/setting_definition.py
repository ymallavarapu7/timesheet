from typing import Any, Optional

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SettingDefinition(Base):
    """
    Global catalog of tenant settings. One row per setting key — shared across
    all tenants. Declares the type, default, validation rules, UI metadata,
    and admin visibility for each setting that a tenant can configure.

    The per-tenant values live in ``TenantSettings``. When a tenant has no
    row for a given key, the ``default_value`` from this catalog is used.
    """

    __tablename__ = "setting_definitions"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    data_type: Mapped[str] = mapped_column(String(20), nullable=False)
    default_value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    validation: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    added_in: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1.0.0", server_default="'1.0.0'"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SettingDefinition({self.key}, {self.data_type})>"
