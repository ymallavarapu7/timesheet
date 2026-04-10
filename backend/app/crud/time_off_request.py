from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import String, asc, cast, desc, func as sa_func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.config import settings

from app.models.time_off_request import TimeOffRequest, TimeOffStatus, TimeOffType
from app.models.user import User
from app.schemas import TimeOffRequestCreate, TimeOffRequestUpdate


async def get_time_off_request_by_id(db: AsyncSession, request_id: int, tenant_id: Optional[int] = None) -> Optional[TimeOffRequest]:
    """Get time off request by ID, scoped to a tenant. Pass tenant_id=None only for PLATFORM_ADMIN."""
    query = select(TimeOffRequest).where(TimeOffRequest.id == request_id)
    if tenant_id is not None:
        query = query.where(TimeOffRequest.tenant_id == tenant_id)
    query = query.options(
        selectinload(TimeOffRequest.user).selectinload(
            User.manager_assignment),
        selectinload(TimeOffRequest.user).selectinload(User.project_access),
    )
    result = await db.execute(query)
    return result.scalars().first()


async def create_time_off_request(
    db: AsyncSession,
    user_id: int,
    tenant_id: int,
    payload: TimeOffRequestCreate,
) -> TimeOffRequest:
    # Enforce backdate limit
    max_backdate = date.today() - timedelta(weeks=settings.time_entry_backdate_weeks)
    if payload.request_date < max_backdate:
        raise ValueError(
            f"Cannot create time off requests more than {settings.time_entry_backdate_weeks} weeks in the past"
        )

    # Check for overlapping requests on the same date
    overlap_count = await db.scalar(
        select(sa_func.count(TimeOffRequest.id)).where(
            (TimeOffRequest.user_id == user_id)
            & (TimeOffRequest.request_date == payload.request_date)
            & (TimeOffRequest.status != TimeOffStatus.REJECTED)
        )
    )
    if overlap_count and overlap_count > 0:
        raise ValueError(
            f"A time off request already exists for {payload.request_date.isoformat()}"
        )

    item = TimeOffRequest(
        user_id=user_id,
        tenant_id=tenant_id,
        created_by=user_id,
        updated_by=user_id,
        **payload.model_dump(),
    )
    db.add(item)
    try:
        await db.commit()
        await db.refresh(item)
    except IntegrityError:
        await db.rollback()
        raise
    return item


async def update_time_off_request(
    db: AsyncSession,
    request_item: TimeOffRequest,
    payload: TimeOffRequestUpdate,
    updated_by: Optional[int] = None,
) -> TimeOffRequest:
    if request_item.status != TimeOffStatus.DRAFT:
        raise ValueError("Can only update DRAFT time off requests")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(request_item, field, value)

    request_item.updated_by = updated_by or request_item.user_id

    db.add(request_item)
    await db.commit()
    await db.refresh(request_item)
    return request_item


async def delete_time_off_request(db: AsyncSession, request_id: int, tenant_id: Optional[int] = None) -> bool:
    request_item = await get_time_off_request_by_id(db, request_id, tenant_id=tenant_id)
    if request_item and request_item.status == TimeOffStatus.DRAFT:
        await db.delete(request_item)
        await db.commit()
        return True
    return False


async def list_user_time_off_requests(
    db: AsyncSession,
    user_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[TimeOffStatus] = None,
    leave_type: Optional[TimeOffType] = None,
    search: Optional[str] = None,
    sort_by: str = "request_date",
    sort_order: str = "desc",
    skip: int = 0,
    limit: int = 100,
) -> list[TimeOffRequest]:
    query = select(TimeOffRequest).where(TimeOffRequest.user_id == user_id)
    query = query.options(
        selectinload(TimeOffRequest.user).selectinload(
            User.manager_assignment),
        selectinload(TimeOffRequest.user).selectinload(User.project_access),
    )

    if start_date:
        query = query.where(TimeOffRequest.request_date >= start_date)
    if end_date:
        query = query.where(TimeOffRequest.request_date <= end_date)
    if status:
        query = query.where(TimeOffRequest.status == status)
    if leave_type:
        query = query.where(TimeOffRequest.leave_type == leave_type)
    if search:
        like = f"%{search.strip()}%"
        query = query.where(or_(TimeOffRequest.reason.ilike(
            like), cast(TimeOffRequest.leave_type, String).ilike(like)))

    sort_map = {
        "request_date": TimeOffRequest.request_date,
        "created_at": TimeOffRequest.created_at,
        "hours": TimeOffRequest.hours,
        "status": TimeOffRequest.status,
    }
    sort_column = sort_map.get(sort_by, TimeOffRequest.request_date)
    query = query.order_by(asc(sort_column) if sort_order ==
                           "asc" else desc(sort_column))

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def submit_time_off_requests(
    db: AsyncSession,
    user_id: int,
    request_ids: list[int],
    submitted_by: Optional[int] = None,
) -> list[TimeOffRequest]:
    query = select(TimeOffRequest).where(
        (TimeOffRequest.user_id == user_id)
        & (TimeOffRequest.id.in_(request_ids))
        & (TimeOffRequest.status == TimeOffStatus.DRAFT)
    )
    query = query.options(
        selectinload(TimeOffRequest.user).selectinload(
            User.manager_assignment),
        selectinload(TimeOffRequest.user).selectinload(User.project_access),
    )
    result = await db.execute(query)
    items = result.scalars().all()

    if not items:
        raise ValueError("No DRAFT time off requests found to submit")

    for item in items:
        item.status = TimeOffStatus.SUBMITTED
        item.submitted_at = datetime.now(timezone.utc)
        item.updated_by = submitted_by or user_id
        db.add(item)

    await db.commit()
    for item in items:
        await db.refresh(item)

    return items


async def list_pending_time_off_approvals(
    db: AsyncSession,
    employee_ids: Optional[list[int]] = None,
    tenant_id: Optional[int] = None,
    search: Optional[str] = None,
    sort_by: str = "request_date",
    sort_order: str = "desc",
    skip: int = 0,
    limit: int = 100,
) -> list[TimeOffRequest]:
    query = select(TimeOffRequest).where(
        TimeOffRequest.status == TimeOffStatus.SUBMITTED)
    if tenant_id is not None:
        query = query.where(TimeOffRequest.tenant_id == tenant_id)
    if employee_ids is not None:
        if not employee_ids:
            return []
        query = query.where(TimeOffRequest.user_id.in_(employee_ids))
    query = query.options(selectinload(TimeOffRequest.user))

    if search:
        like = f"%{search.strip()}%"
        query = query.join(User, User.id == TimeOffRequest.user_id).where(
            or_(
                TimeOffRequest.reason.ilike(like),
                cast(TimeOffRequest.leave_type, String).ilike(like),
                User.full_name.ilike(like),
            )
        )

    sort_map = {
        "request_date": TimeOffRequest.request_date,
        "submitted_at": TimeOffRequest.submitted_at,
        "hours": TimeOffRequest.hours,
        "employee": User.full_name,
    }

    if sort_by == "employee":
        query = query.join(User, User.id == TimeOffRequest.user_id)

    sort_column = sort_map.get(sort_by, TimeOffRequest.request_date)
    query = query.order_by(asc(sort_column) if sort_order ==
                           "asc" else desc(sort_column))

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def approve_time_off_request(
    db: AsyncSession,
    request_id: int,
    approved_by_id: int,
    tenant_id: Optional[int] = None,
) -> TimeOffRequest:
    item = await get_time_off_request_by_id(db, request_id, tenant_id=tenant_id)
    if not item:
        raise ValueError("Time off request not found")
    if item.status != TimeOffStatus.SUBMITTED:
        raise ValueError("Can only approve SUBMITTED time off requests")

    item.status = TimeOffStatus.APPROVED
    item.approved_by = approved_by_id
    item.approved_at = datetime.now(timezone.utc)
    item.rejection_reason = None
    item.updated_by = approved_by_id

    db.add(item)
    await db.commit()
    return await get_time_off_request_by_id(db, request_id, tenant_id=tenant_id)


async def reject_time_off_request(
    db: AsyncSession,
    request_id: int,
    approved_by_id: int,
    rejection_reason: str,
    tenant_id: Optional[int] = None,
) -> TimeOffRequest:
    item = await get_time_off_request_by_id(db, request_id, tenant_id=tenant_id)
    if not item:
        raise ValueError("Time off request not found")
    if item.status != TimeOffStatus.SUBMITTED:
        raise ValueError("Can only reject SUBMITTED time off requests")

    item.status = TimeOffStatus.REJECTED
    item.approved_by = approved_by_id
    item.approved_at = datetime.now(timezone.utc)
    item.rejection_reason = rejection_reason
    item.updated_by = approved_by_id

    db.add(item)
    await db.commit()
    return await get_time_off_request_by_id(db, request_id, tenant_id=tenant_id)
