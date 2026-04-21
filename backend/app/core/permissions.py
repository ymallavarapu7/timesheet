from __future__ import annotations

from datetime import date
from typing import Optional
import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import Role, RolePermission
from app.models.role_assignment import RoleAssignment
from app.models.user import User

logger = logging.getLogger(__name__)


async def get_user_permissions(
    db: AsyncSession,
    user: User,
    as_of: Optional[date] = None,
) -> frozenset[str]:
    """
    Return the active permission codes for ``user`` as of ``as_of``.
    """
    as_of = as_of or date.today()
    result = await db.execute(
        select(RolePermission.permission_code)
        .join(Role, RolePermission.role_id == Role.id)
        .join(RoleAssignment, RoleAssignment.role_id == Role.id)
        .where(
            RoleAssignment.user_id == user.id,
            RoleAssignment.effective_from <= as_of,
            or_(
                RoleAssignment.effective_to.is_(None),
                RoleAssignment.effective_to > as_of,
            ),
        )
        .distinct()
    )
    return frozenset(result.scalars().all())


async def user_has_permission(
    db: AsyncSession,
    user: User,
    permission: str,
    as_of: Optional[date] = None,
) -> bool:
    perms = await get_user_permissions(db, user, as_of)
    return permission in perms


async def shadow_check(
    db: AsyncSession,
    user: User,
    permission: str,
    old_decision: bool,
    context: str = "",
) -> None:
    """
    Run the new permission check without affecting the old role-based outcome.
    """
    try:
        new_decision = await user_has_permission(db, user, permission)
        if new_decision != old_decision:
            logger.warning(
                "SHADOW_MISMATCH permission=%r user=%s role=%s old=%s new=%s context=%s",
                permission,
                user.id,
                user.role.value,
                old_decision,
                new_decision,
                context,
            )
    except Exception as exc:  # pragma: no cover - defensive path
        logger.error(
            "SHADOW_ERROR permission=%r user=%s error=%s",
            permission,
            user.id,
            exc,
        )
