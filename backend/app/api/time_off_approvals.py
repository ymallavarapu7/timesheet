from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_tenant_db, require_role
from app.services.notification_emails import notify_time_off_approved, notify_time_off_rejected
from app.services.activity import (
    TENANT_ADMIN_ACTIVITY_SCOPE,
    build_activity_event,
    record_activity_events,
)
from app.crud.time_off_request import (
    approve_time_off_request,
    get_time_off_request_by_id,
    list_pending_time_off_approvals,
    reject_time_off_request,
)
from app.models.assignments import EmployeeManagerAssignment
from app.models.time_off_request import TimeOffRequest, TimeOffStatus
from app.models.user import User, UserRole
from app.schemas import (
    TimeOffApproveRequest,
    TimeOffRejectRequest,
    TimeOffRequestResponse,
    TimeOffRequestWithUser,
)

router = APIRouter(prefix="/time-off-approvals", tags=["time-off-approvals"])
APPROVAL_HISTORY_TTL_DAYS = 7


async def _get_direct_report_ids(db: AsyncSession, manager_user_id: int) -> list[int]:
    result = await db.execute(
        select(EmployeeManagerAssignment.employee_id)
        .where(EmployeeManagerAssignment.manager_id == manager_user_id)
    )
    return list(result.scalars().all())


@router.get("/pending", response_model=list[TimeOffRequestWithUser])
async def get_pending_time_off(
    search: str | None = Query(None),
    sort_by: str = Query(
        "request_date", pattern="^(request_date|submitted_at|hours|employee)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role(
        "MANAGER", "ADMIN")),
):
    employee_ids = None
    if current_user.role != UserRole.ADMIN:
        assigned_employee_ids = await _get_direct_report_ids(db, current_user.id)
        employee_ids = assigned_employee_ids or []

    return await list_pending_time_off_approvals(
        db,
        employee_ids=employee_ids,
        tenant_id=current_user.tenant_id,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )


@router.get("/history", response_model=list[TimeOffRequestWithUser])
async def get_time_off_approval_history(
    search: str | None = Query(None),
    sort_by: str = Query(
        "approved_at", pattern="^(approved_at|request_date|hours|employee|status)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    include_older: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role(
        "MANAGER", "ADMIN")),
) -> list[TimeOffRequest]:
    employee_ids = None
    if current_user.role != UserRole.ADMIN:
        assigned_employee_ids = await _get_direct_report_ids(db, current_user.id)
        employee_ids = assigned_employee_ids or []

    query = (
        select(TimeOffRequest)
        .options(selectinload(TimeOffRequest.user))
        .where(TimeOffRequest.status.in_([TimeOffStatus.APPROVED, TimeOffStatus.REJECTED]))
        .where(TimeOffRequest.tenant_id == current_user.tenant_id)
    )

    if employee_ids is not None:
        if not employee_ids:
            return []
        query = query.where(TimeOffRequest.user_id.in_(employee_ids))

    if not include_older:
        cutoff = datetime.now(timezone.utc) - timedelta(days=APPROVAL_HISTORY_TTL_DAYS)
        query = query.where(TimeOffRequest.updated_at >= cutoff)

    joined_user = False
    if search:
        search_value = f"%{search.strip()}%"
        query = query.join(TimeOffRequest.user).where(
            or_(
                User.full_name.ilike(search_value),
                TimeOffRequest.reason.ilike(search_value),
                TimeOffRequest.rejection_reason.ilike(search_value),
            )
        )
        joined_user = True

    sort_column_map = {
        "approved_at": TimeOffRequest.approved_at,
        "request_date": TimeOffRequest.request_date,
        "hours": TimeOffRequest.hours,
        "employee": User.full_name,
        "status": TimeOffRequest.status,
    }
    sort_column = sort_column_map.get(sort_by, TimeOffRequest.approved_at)
    if sort_by == "employee" and not joined_user:
        query = query.join(TimeOffRequest.user)

    if sort_order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/{request_id}/approve", response_model=TimeOffRequestResponse)
async def approve_time_off_item(
    request_id: int,
    approve_request: TimeOffApproveRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role(
        "MANAGER", "ADMIN")),
):
    item = await get_time_off_request_by_id(db, request_id, tenant_id=current_user.tenant_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Time off request not found")

    if current_user.role != UserRole.ADMIN and item.user_id not in await _get_direct_report_ids(db, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only approve requests for your direct reports",
        )

    try:
        approved = await approve_time_off_request(db, request_id, current_user.id, tenant_id=current_user.tenant_id)

        # Audit: time off approved
        await record_activity_events(db, [build_activity_event(
            activity_type="TIME_OFF_APPROVED",
            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
            tenant_id=current_user.tenant_id,
            actor_user=current_user,
            entity_type="time_off_request",
            entity_id=request_id,
            summary=f"{current_user.full_name} approved time off request #{request_id} for employee {item.user_id}.",
            route="/time-off-approvals",
            metadata={"employee_id": item.user_id},
        )])

        # Email notification to employee
        if item.user and item.user.email:
            await notify_time_off_approved(
                employee_email=item.user.email,
                employee_name=item.user.full_name,
                approver_name=current_user.full_name,
                leave_type=str(item.leave_type.value if hasattr(item.leave_type, 'value') else item.leave_type),
                start_date=str(item.start_date),
                end_date=str(item.end_date),
                db=db,
            )

        return approved
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{request_id}/reject", response_model=TimeOffRequestResponse)
async def reject_time_off_item(
    request_id: int,
    reject_request: TimeOffRejectRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role(
        "MANAGER", "ADMIN")),
):
    item = await get_time_off_request_by_id(db, request_id, tenant_id=current_user.tenant_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Time off request not found")

    if current_user.role != UserRole.ADMIN and item.user_id not in await _get_direct_report_ids(db, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only reject requests for your direct reports",
        )

    try:
        rejected = await reject_time_off_request(
            db,
            request_id,
            current_user.id,
            reject_request.rejection_reason,
            tenant_id=current_user.tenant_id,
        )

        # Audit: time off rejected
        await record_activity_events(db, [build_activity_event(
            activity_type="TIME_OFF_REJECTED",
            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
            tenant_id=current_user.tenant_id,
            actor_user=current_user,
            entity_type="time_off_request",
            entity_id=request_id,
            summary=f"{current_user.full_name} rejected time off request #{request_id} for employee {item.user_id}.",
            route="/time-off-approvals",
            metadata={"employee_id": item.user_id, "reason": reject_request.rejection_reason},
        )])

        # Email notification to employee
        if item.user and item.user.email:
            await notify_time_off_rejected(
                employee_email=item.user.email,
                employee_name=item.user.full_name,
                rejector_name=current_user.full_name,
                leave_type=str(item.leave_type.value if hasattr(item.leave_type, 'value') else item.leave_type),
                start_date=str(item.start_date),
                end_date=str(item.end_date),
                reason=reject_request.rejection_reason,
                db=db,
            )

        return rejected
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
