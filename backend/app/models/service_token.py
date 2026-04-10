from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class ServiceToken(Base, TimestampMixin):
    __tablename__ = "service_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Human-readable name for this token
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # The token value (stored as bcrypt hash — never store plaintext)
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
