from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class ServiceToken(Base, TimestampMixin):
    __tablename__ = "service_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Human-readable name for this token
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Public token id; full token is "<token_id>.<secret>". NULL for
    # pre-041 legacy tokens (validated via loop fallback).
    token_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, unique=True, index=True
    )

    # bcrypt hash of the secret half (or the whole token, for legacy rows).
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Scoped to a specific tenant
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )

    # Which system this token belongs to
    # e.g. 'ingestion_platform'
    issuer: Mapped[str] = mapped_column(String(100), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_used_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
