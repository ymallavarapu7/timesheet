"""Control-plane SQLAlchemy models.

Holds cross-tenant data only: tenants directory, platform-admin
accounts, platform settings, and provisioning audit logs. Tables in
this package are bound to ``ControlBase`` so they never end up in a
tenant database, even by accident.
"""
from sqlalchemy.orm import DeclarativeBase

from app.models.base import TimestampMixin  # re-exported for control models


class ControlBase(DeclarativeBase):
    """Base class for control-plane SQLAlchemy models.

    Separate from ``app.models.base.Base`` so that the per-tenant
    metadata and the control-plane metadata never share migrations or
    ``create_all`` calls. A model on the wrong base class is the kind
    of bug that takes down the wrong database.
    """


# Importing the model modules below registers their tables with
# ``ControlBase.metadata`` at module import time. ``app/db_control.py``
# imports this package once, which is enough to populate the metadata.
from app.models.control.platform_admin import PlatformAdmin  # noqa: F401, E402
from app.models.control.tenant import ControlTenant  # noqa: F401, E402
from app.models.control.platform_settings import ControlPlatformSettings  # noqa: F401, E402
from app.models.control.tenant_provisioning_job import TenantProvisioningJob  # noqa: F401, E402

__all__ = [
    "ControlBase",
    "TimestampMixin",
    "ControlTenant",
    "PlatformAdmin",
    "ControlPlatformSettings",
    "TenantProvisioningJob",
]
