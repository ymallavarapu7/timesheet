"""Audit log of tenant provisioning operations.

Every "create tenant", "run migration", or "deactivate tenant" run
gets a row here with start/finish timestamps, the alembic revision it
landed on, and the outcome. This is the system of record for "what
state is this tenant's database in?" and is what the migration runner
reads when deciding whether a tenant needs another upgrade pass.

Phase 3.A creates the table but only the future provisioning script
writes to it; we don't backfill historical rows.
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
    # Alembic revision the tenant DB landed on after the run. Used by
    # the migration runner to detect tenants stuck on an old revision.
    alembic_revision: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    # Free-text error captured when status == failed. Long enough for a
    # full Python traceback if we want it.
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<TenantProvisioningJob(id={self.id}, tenant_id={self.tenant_id}, "
            f"kind={self.kind}, status={self.status})>"
        )
