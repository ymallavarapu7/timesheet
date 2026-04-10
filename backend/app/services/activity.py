from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog
from app.models.user import User

TENANT_ADMIN_ACTIVITY_SCOPE = "TENANT_ADMIN"
PLATFORM_ADMIN_ACTIVITY_SCOPE = "PLATFORM_ADMIN"


async def record_activity_events(
    db: AsyncSession,
    events: Iterable[dict[str, Any]],
) -> None:
    pending_events = [event for event in events if event.get("summary")]
    if not pending_events:
        return

    for event in pending_events:
        db.add(ActivityLog(**event))

    await db.commit()


def build_activity_event(
    *,
    activity_type: str,
    visibility_scope: str,
    entity_type: str,
    summary: str,
    route: str,
    actor_user: User | None = None,
    tenant_id: int | None = None,
    entity_id: int | None = None,
    route_params: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    severity: str = "info",
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "actor_user_id": actor_user.id if actor_user else None,
        "actor_name": actor_user.full_name if actor_user else None,
        "activity_type": activity_type,
        "visibility_scope": visibility_scope,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "summary": summary,
        "route": route,
        "route_params": route_params,
        "metadata_json": metadata,
        "severity": severity,
    }
