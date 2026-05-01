from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class ServiceToken(Base, TimestampMixin):
    __tablename__ = "service_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Human-readable name for this token
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Public, opaque, unique token identifier. The full token surfaced
    # to callers is ``<token_id>.<secret>``; we look up the row by
    # token_id (one indexed query) and bcrypt-verify the secret. NULL
    # for legacy tokens issued before migration 041 — those still
    # validate via the loop fallback in ``get_service_token_tenant``.
    token_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, unique=True, index=True
    )

    # The secret-half of the token, stored as a bcrypt hash. The
    # historical loop fallback bcrypt-compared the entire raw token
    # against this column; for tokens with a token_id we now compare
    # only the secret portion.
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
