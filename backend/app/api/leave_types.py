import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db import get_db
from app.models.leave_type import LeaveType
from app.models.user import User
from app.schemas import LeaveTypeCreate, LeaveTypeResponse, LeaveTypeUpdate

router = APIRouter(prefix="/leave-types", tags=["leave-types"])


def _derive_code(label: str) -> str:
    """Turn a human label into a stable uppercase-snake-case code."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").upper()
    return (cleaned or "LEAVE")[:50]


@router.get("", response_model=list[LeaveTypeResponse])
async def list_leave_types(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[LeaveType]:
    """Any authenticated user can read their tenant's leave types."""
    if current_user.tenant_id is None:
        return []
    q = select(LeaveType).where(LeaveType.tenant_id == current_user.tenant_id)
    if not include_inactive:
        q = q.where(LeaveType.is_active.is_(True))
    q = q.order_by(LeaveType.label.asc())
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("", response_model=LeaveTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_leave_type(
    body: LeaveTypeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> LeaveType:
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant context required")
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Label cannot be empty")
    code = (body.code or _derive_code(label)).strip().upper()
    color = (body.color or "#6b7280").strip()
    lt = LeaveType(tenant_id=current_user.tenant_id, code=code, label=label, color=color, is_active=True)
    db.add(lt)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Leave type with that code already exists")
    await db.refresh(lt)
    return lt


@router.patch("/{leave_type_id}", response_model=LeaveTypeResponse)
async def update_leave_type(
    leave_type_id: int,
    body: LeaveTypeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> LeaveType:
    result = await db.execute(select(LeaveType).where(LeaveType.id == leave_type_id))
    lt = result.scalar_one_or_none()
    if lt is None or lt.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave type not found")
    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(lt, field, value)
    db.add(lt)
    await db.commit()
    await db.refresh(lt)
    return lt


@router.delete("/{leave_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_leave_type(
    leave_type_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> None:
    """Hard-delete a leave type. Blocked if any time-off requests reference it;
    deactivate instead in that case."""
    from app.models.time_off_request import TimeOffRequest
    from sqlalchemy import func
    result = await db.execute(select(LeaveType).where(LeaveType.id == leave_type_id))
    lt = result.scalar_one_or_none()
    if lt is None or lt.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave type not found")
    in_use = await db.scalar(
        select(func.count(TimeOffRequest.id)).where(
            (TimeOffRequest.tenant_id == current_user.tenant_id)
            & (TimeOffRequest.leave_type == lt.code)
        )
    )
    if in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete — {in_use} time-off request(s) use this type. Deactivate it instead.",
        )
    await db.delete(lt)
    await db.commit()
