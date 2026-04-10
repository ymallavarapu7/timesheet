from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UserNotificationState(Base):
    __tablename__ = "user_notification_states"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), primary_key=True)
    notification_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)


class UserNotificationDismissal(Base):
    __tablename__ = "user_notification_dismissals"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), primary_key=True)
    notification_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)
