from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class UserEmailAlias(Base):
    """Additional emails attached to a User for ingestion address matching.

    The primary email lives on ``users.email`` and is the login + the one
    notifications go to. Aliases are matched by the ingestion resolver
    (sender / forwarded-from / chain) and by ``get_user_by_email`` so an
    admin renaming a person's primary email doesn't break inbound routing.
    """

    __tablename__ = "user_email_aliases"
    __table_args__ = (
        UniqueConstraint("email", name="uq_user_email_alias_email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user = relationship("User", back_populates="email_aliases")
