"""
Monthly license re-verification arq job.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version

from sqlalchemy import func, select

from app.core.config import settings

logger = logging.getLogger(__name__)


async def reverify_license(ctx: dict) -> None:
    del ctx

    if settings.DEPLOYMENT_MODE != "self_hosted":
        return

    from app.core.licensing.state import (
        get_license_state,
        persist_license_state,
        set_license_state,
    )
    from app.core.licensing.validator import (
        LicenseState,
        LicenseStatus,
        get_license_key,
        local_validate,
        online_validate,
    )
    from app.db import AsyncSessionLocal
    from app.models.user import User

    key = get_license_key()
    if not key:
        logger.error("license reverify: no license key found")
        return

    local_state = local_validate(key)
    if local_state.status == LicenseStatus.INVALID:
        logger.error("license reverify: local validation failed: %s", local_state.message)
        set_license_state(local_state)
        await persist_license_state(local_state)
        return

    try:
        app_version = pkg_version("timesheet-app")
    except Exception:
        app_version = "unknown"

    async with AsyncSessionLocal() as db:
        active_users = await db.scalar(
            select(func.count(User.id)).where(User.is_active == True)  # noqa: E712
        )

    current = get_license_state()
    new_state = await online_validate(key, local_state, active_users or 0, app_version)

    if new_state.status == LicenseStatus.GRACE:
        if current.status != LicenseStatus.GRACE:
            logger.warning(
                "LICENSE GRACE WINDOW STARTED - online validation failed. "
                "License will expire in %d days if not resolved. "
                "Grace until: %s",
                settings.LICENSE_GRACE_PERIOD_DAYS,
                new_state.grace_until,
            )
        elif current.grace_until and datetime.now(timezone.utc) > current.grace_until:
            new_state = LicenseState(
                status=LicenseStatus.EXPIRED,
                jti=current.jti,
                tier=current.tier,
                max_users=current.max_users,
                features=current.features,
                grace_until=current.grace_until,
                message="Grace period elapsed",
            )
            logger.error(
                "LICENSE EXPIRED - grace period elapsed. "
                "Application entering degraded mode."
            )

    set_license_state(new_state)
    await persist_license_state(new_state)
    logger.info(
        "license reverify complete: status=%s active_users=%s",
        new_state.status,
        active_users,
    )
