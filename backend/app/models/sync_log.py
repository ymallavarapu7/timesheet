from sqlalchemy import String, Text, Enum as SAEnum, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin
import enum


class SyncDirection(str, enum.Enum):
    inbound = "inbound"    # ingestion platform → timesheet app
    outbound = "outbound"  # timesheet app → ingestion platform


class SyncEntityType(str, enum.Enum):
    user = "user"
    client = "client"
    project = "project"
    time_entry = "time_entry"
    timesheet = "timesheet"


class SyncStatus(str, enum.Enum):
    success = "success"
    failed = "failed"
    skipped = "skipped"    # entity already up to date; no action needed
    partial = "partial"    # some line items succeeded, some failed


class SyncLog(Base, TimestampMixin):
    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Which tenant this sync event belongs to
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )

    # Direction and entity type
    direction: Mapped[SyncDirection] = mapped_column(
        SAEnum(SyncDirection), nullable=False
    )
    entity_type: Mapped[SyncEntityType] = mapped_column(
        SAEnum(SyncEntityType), nullable=False
    )

    # IDs on both sides — whichever are known at time of logging
    local_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ingestion_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Result
    status: Mapped[SyncStatus] = mapped_column(
        SAEnum(SyncStatus), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Full request payload (inbound) or outgoing payload (outbound)
    # Stored as JSON string for debugging
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    # What action was taken
    action: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    # e.g. 'created', 'updated', 'skipped_duplicate', 'upserted'
