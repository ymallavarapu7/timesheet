from sqlalchemy import ForeignKey, String, UniqueConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class LeaveType(Base, TimestampMixin):
    """A tenant-defined leave type (e.g. PTO, Sick Day, Paternity Leave).

    `code` is the stable identifier stored on time_off_requests.leave_type.
    `label` is what admins/employees see in the UI.
    `is_active = False` retires a type without deleting rows that reference it.
    """

    __tablename__ = "leave_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_leave_types_tenant_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#6b7280")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    tenant: Mapped["Tenant"] = relationship("Tenant")
