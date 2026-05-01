"""Audit log of tenant provisioning operations.

System of record for tenant DB state; the migration runner reads it
to decide whether a tenant needs another upgrade pass.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.models.control import ControlBase


class ProvisioningJobKind(str, enum.Enum):
    create = "create"
    migrate = "migrate"
    deactivate = "deactivate"


class ProvisioningJobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class TenantProvisioningJob(ControlBase, TimestampMixin):
    """A single provisioning attempt for a given tenant."""

    __tablename__ = "tenant_provisioning_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    kind: Mapped[ProvisioningJobKind] = mapped_column(
        SAEnum(ProvisioningJobKind, name="provisioning_job_kind"),
        nullable=False,
    )
    status: Mapped[ProvisioningJobStatus] = mapped_column(
        SAEnum(ProvisioningJobStatus, name="provisioning_job_status"),
        default=ProvisioningJobStatus.pending,
        nullable=False,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    alembic_revision: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<TenantProvisioningJob(id={self.id}, tenant_id={self.tenant_id}, "
            f"kind={self.kind}, status={self.status})>"
        )
