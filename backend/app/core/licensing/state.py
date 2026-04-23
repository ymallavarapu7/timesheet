"""
In-process license state cache and persistence helpers.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from app.core.licensing.validator import LicenseState, LicenseStatus

_current_state: Optional[LicenseState] = None


def get_license_state() -> LicenseState:
    if _current_state is None:
        return LicenseState(
            status=LicenseStatus.MISSING,
            message="License not yet validated",
        )
    return _current_state


def set_license_state(state: LicenseState) -> None:
    global _current_state
    _current_state = state


def is_saas_mode() -> bool:
    from app.core.config import settings

    return settings.DEPLOYMENT_MODE == "saas"


async def persist_license_state(state: LicenseState) -> None:
    if is_saas_mode():
        return

    from app.db import AsyncSessionLocal
    from app.models.tenant import Tenant

    async with AsyncSessionLocal() as db:
        tenant = await db.scalar(select(Tenant).limit(1))
        if tenant is None:
            return
        tenant.deployment_type = "self_hosted"
        tenant.license_jti = state.jti
        tenant.license_grace_until = state.grace_until
        db.add(tenant)
        await db.commit()


async def get_license_expiry_behavior() -> str:
    try:
        from app.db import AsyncSessionLocal
        from app.models.tenant import Tenant

        async with AsyncSessionLocal() as db:
            row = await db.scalar(select(Tenant.license_expiry_behavior).limit(1))
            return row or "read_only"
    except Exception:
        return "read_only"
