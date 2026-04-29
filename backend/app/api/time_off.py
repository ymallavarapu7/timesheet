from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_tenant_db
from app.crud.time_off_request import (
    create_time_off_request,
    delete_time_off_request,
    get_time_off_request_by_id,
    list_user_time_off_requests,
    submit_time_off_requests,
    update_time_off_request,
)
from app.models.time_entry import TimeEntry
from app.models.time_off_request import TimeOffStatus, TimeOffType
from app.models.user import User
from app.schemas import (
    TimeOffRequestCreate,
    TimeOffRequestResponse,
    TimeOffRequestUpdate,
    TimeOffRequestWithUser,
    TimeOffSubmitRequest,
)

router = APIRouter(prefix="/time-off", tags=["time-off"])


@router.get("/my", response_model=list[TimeOffRequestWithUser])
async def get_my_time_off(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    status: Optional[TimeOffStatus] = Query(None),
    leave_type: Optional[TimeOffType] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query(
        "request_date", pattern="^(request_date|created_at|hours|status)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    return await list_user_time_off_requests(
        db,
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        status=status,
        leave_type=leave_type,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )


@router.get("/{request_id}", response_model=TimeOffRequestWithUser)
async def get_time_off_item(
    request_id: int,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    item = await get_time_off_request_by_id(db, request_id, tenant_id=current_user.tenant_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Time off request not found")

    if item.user_id != current_user.id and current_user.role.value == "EMPLOYEE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return item


@router.post("", response_model=TimeOffRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_time_off_item(
    payload: TimeOffRequestCreate,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    # Any tenanted user can request their own time off. Platform admins aren't
    # scoped to a tenant and have no reason to create time-off here.
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admins cannot create time off requests.",
        )

    # Prevent creating time-off on a date that already has time entries
    existing_result = await db.execute(
        select(TimeEntry.id).where(
            (TimeEntry.user_id == current_user.id) &
            (TimeEntry.tenant_id == current_user.tenant_id) &
            (TimeEntry.entry_date == payload.request_date) &
            (TimeEntry.status != "REJECTED")
        ).limit(1)
    )
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A time entry already exists for this date. Cannot add time off on the same day.",
        )

    return await create_time_off_request(db, current_user.id, current_user.tenant_id, payload)


@router.put("/{request_id}", response_model=TimeOffRequestResponse)
async def update_time_off_item(
    request_id: int,
    payload: TimeOffRequestUpdate,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    item = await get_time_off_request_by_id(db, request_id, tenant_id=current_user.tenant_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Time off request not found")
    if item.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Can only edit your own requests")
    if item.status != TimeOffStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Can only edit DRAFT requests")

    return await update_time_off_request(db, item, payload, updated_by=current_user.id)


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_time_off_item(
    request_id: int,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    item = await get_time_off_request_by_id(db, request_id, tenant_id=current_user.tenant_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Time off request not found")
    if item.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Can only delete your own requests")

    success = await delete_time_off_request(db, request_id, tenant_id=current_user.tenant_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Can only delete DRAFT requests")


@router.post("/submit", response_model=list[TimeOffRequestResponse])
async def submit_time_off(
    submit_request: TimeOffSubmitRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await submit_time_off_requests(
            db,
            current_user.id,
            submit_request.request_ids,
            submitted_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
