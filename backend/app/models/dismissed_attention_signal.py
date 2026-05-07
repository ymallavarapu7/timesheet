from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DismissedAttentionSignal(Base):
    """A user-specific dismissal or snooze of a dashboard attention card.

    `signal_key` is a deterministic identifier the frontend produces from
    the action-queue row (e.g. ``users-no-manager``, ``activity-warn-42``).
    `snoozed_until` NULL means "permanently dismissed for this session";
    a future timestamp means "hidden until then, then reappears".
    """

    __tablename__ = "dismissed_attention_signals"
    __table_args__ = (
        UniqueConstraint("user_id", "signal_key", name="uq_dismissed_user_signal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_key: Mapped[str] = mapped_column(String(128), nullable=False)
    snoozed_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
