from datetime import datetime
import enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base


class SenderMatchType(str, enum.Enum):
    email = "email"
    domain = "domain"


class EmailSenderMapping(Base):
    __tablename__ = "email_sender_mappings"
    __table_args__ = (
        Index("ix_email_sender_mappings_lookup", "tenant_id", "match_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    match_type: Mapped[SenderMatchType] = mapped_column(
        SAEnum(SenderMatchType, name="sendermatchtype"), nullable=False
    )
    match_value: Mapped[str] = mapped_column(String(255), nullable=False)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id"), nullable=False
    )
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tenant: Mapped["Tenant"] = relationship("Tenant")
    client: Mapped["Client"] = relationship("Client")
    employee: Mapped["User | None"] = relationship("User")
