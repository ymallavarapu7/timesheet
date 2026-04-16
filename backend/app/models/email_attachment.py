from datetime import datetime
import enum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base


class ExtractionMethod(str, enum.Enum):
    native_pdf = "native_pdf"
    native_spreadsheet = "native_spreadsheet"
    tesseract = "tesseract"
    vision_api = "vision_api"
    llm_structured = "llm_structured"


class ExtractionStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class EmailAttachment(Base):
    __tablename__ = "email_attachments"
    __table_args__ = (
        Index("ix_email_attachments_is_timesheet", "is_timesheet"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email_id: Mapped[int] = mapped_column(
        ForeignKey("ingested_emails.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_timesheet: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    extraction_method: Mapped[ExtractionMethod | None] = mapped_column(
        SAEnum(ExtractionMethod, name="extractionmethod"), nullable=True
    )
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        SAEnum(ExtractionStatus, name="extractionstatus"),
        default=ExtractionStatus.pending,
        nullable=False,
    )
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured preview for the reviewer UI (spreadsheets only). Shape:
    # {"sheets": [{"name": str, "rows": [[str, ...], ...]}]}.
    spreadsheet_preview: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Self-contained HTML rendering of the source file for reviewer display.
    # Populated for spreadsheets; future formats may also use this.
    rendered_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    email: Mapped["IngestedEmail"] = relationship(
        "IngestedEmail", back_populates="attachments"
    )
    ingestion_timesheets: Mapped[list["IngestionTimesheet"]] = relationship(
        "IngestionTimesheet", back_populates="attachment",
        cascade="all, delete-orphan", passive_deletes=True,
    )
