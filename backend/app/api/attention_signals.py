"""Per-user dismissal/snooze of dashboard attention-queue cards.

The attention queue itself is computed on the frontend from data we
already serve (users, notifications, recent activity). Dismissals are
the only state we need to persist server-side so they survive a page
refresh and can carry a future ``snoozed_until`` timestamp.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.deps import get_current_user, get_tenant_db
from app.models import DismissedAttentionSignal, User

router = APIRouter(prefix="/attention-signals", tags=["attention-signals"])


class DismissedSignalRead(BaseModel):
    signal_key: str
    snoozed_until: Optional[str] = None


class DismissRequest(BaseModel):
    signal_key: str = Field(..., min_length=1, max_length=128)
    snoozed_until: Optional[datetime] = None


@router.get("/dismissed", response_model=list[DismissedSignalRead])
async def list_dismissed(
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
) -> list[DismissedSignalRead]:
    """Return non-expired dismissals for the current user."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(DismissedAttentionSignal).where(
            DismissedAttentionSignal.user_id == current_user.id,
        )
    )
    out: list[DismissedSignalRead] = []
    expired_ids: list[int] = []
    for row in result.scalars().all():
        if row.snoozed_until is not None and row.snoozed_until <= now:
            expired_ids.append(row.id)
            continue
        out.append(DismissedSignalRead(
            signal_key=row.signal_key,
            snoozed_until=row.snoozed_until.isoformat() if row.snoozed_until else None,
        ))
    if expired_ids:
        await db.execute(
            delete(DismissedAttentionSignal).where(
                DismissedAttentionSignal.id.in_(expired_ids)
            )
        )
        await db.commit()
    return out


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_signal(
    body: DismissRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Dismiss or snooze a signal for the current user (upsert)."""
    stmt = pg_insert(DismissedAttentionSignal).values(
        user_id=current_user.id,
        signal_key=body.signal_key,
        snoozed_until=body.snoozed_until,
    ).on_conflict_do_update(
        index_elements=["user_id", "signal_key"],
        set_={"snoozed_until": body.snoozed_until},
    )
    await db.execute(stmt)
    await db.commit()


@router.delete("/{signal_key}", status_code=status.HTTP_204_NO_CONTENT)
async def undismiss_signal(
    signal_key: str,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Remove a dismissal/snooze (e.g., user wants to see the card again)."""
    await db.execute(
        delete(DismissedAttentionSignal).where(
            DismissedAttentionSignal.user_id == current_user.id,
            DismissedAttentionSignal.signal_key == signal_key,
        )
    )
    await db.commit()
