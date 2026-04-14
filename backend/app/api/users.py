from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.schemas import UserResponse, UserCreate, UserUpdate, UserSelfUpdate, UserProfileResponse, ChangePasswordRequest, MessageResponse, UserCreateResponse
from app.crud.user import get_user_by_id, create_user, update_user, delete_user, list_users
from app.core.deps import get_current_user, require_role, require_same_tenant
from app.models.user import User
from app.models.assignments import EmployeeManagerAssignment
from app.core.security import verify_password, get_password_hash
from app.models.user import UserRole
from app.crud.tenant import get_tenant
from app.services.ingestion_sync import _send_outbound_webhook
from app.services.activity import (
    PLATFORM_ADMIN_ACTIVITY_SCOPE,
    TENANT_ADMIN_ACTIVITY_SCOPE,
    build_activity_event,
    record_activity_events,
)
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/users", tags=["users"])

MANAGER_CHAIN_ROLES = {UserRole.MANAGER, UserRole.SENIOR_MANAGER, UserRole.CEO}


async def _get_descendant_user_ids(db: AsyncSession, manager_id: int) -> set[int]:
    descendant_ids: set[int] = set()
    frontier: set[int] = {manager_id}

    while frontier:
        result = await db.execute(
            select(EmployeeManagerAssignment.employee_id)
            .where(EmployeeManagerAssignment.manager_id.in_(frontier))
        )
        children = set(result.scalars().all())
        next_frontier = children - descendant_ids
        descendant_ids.update(next_frontier)
        frontier = next_frontier

    return descendant_ids


async def _get_managed_employees(db: AsyncSession, manager_id: int, tenant_id: int) -> list[User]:
    descendant_ids = await _get_descendant_user_ids(db, manager_id)
    if not descendant_ids:
        return []

    result = await db.execute(
        select(User)
        .where(User.id.in_(descendant_ids))
        .where(User.role == UserRole.EMPLOYEE)
        .where(User.tenant_id == tenant_id)
        .options(
            selectinload(User.manager_assignment),
            selectinload(User.project_access),
        )
        .order_by(User.full_name.asc())
    )
    return list(result.scalars().all())


async def _get_managed_users(db: AsyncSession, manager_id: int, tenant_id: int) -> list[User]:
    descendant_ids = await _get_descendant_user_ids(db, manager_id)
    if not descendant_ids:
        return []

    result = await db.execute(
        select(User)
        .where(User.id.in_(descendant_ids))
        .where(User.tenant_id == tenant_id)
        .options(
            selectinload(User.manager_assignment),
            selectinload(User.project_access),
        )
        .order_by(User.full_name.asc())
    )
    return list(result.scalars().all())


def _validate_new_password(password: str) -> None:
    from app.core.password_policy import validate_password
    error = validate_password(password)
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )


@router.get("", response_model=list[UserResponse])
async def list_all_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[User]:
    """
    List users.
    - PLATFORM_ADMIN: all users across all tenants
    - Admin: all users within their tenant
    - Manager chain roles: employees in their reporting tree (within their tenant)
    """
    if current_user.role == UserRole.PLATFORM_ADMIN:
        result = await db.execute(
            select(User)
            .options(
                selectinload(User.manager_assignment),
                selectinload(User.project_access),
            )
            .order_by(User.full_name.asc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    if current_user.role == UserRole.ADMIN:
        return await list_users(db, tenant_id=current_user.tenant_id, skip=skip, limit=limit)

    if current_user.role in MANAGER_CHAIN_ROLES:
        managed_users = await _get_managed_users(db, current_user.id, current_user.tenant_id)
        return managed_users[skip: skip + limit]

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied",
    )


@router.get("/me/profile", response_model=UserProfileResponse)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return the logged-in user's read-only profile fields."""
    direct_reports_result = await db.execute(
        select(User)
        .join(EmployeeManagerAssignment, EmployeeManagerAssignment.employee_id == User.id)
        .where(EmployeeManagerAssignment.manager_id == current_user.id)
        .order_by(User.full_name.asc())
    )
    direct_reports = list(direct_reports_result.scalars().all())

    manager_name = None
    manager_user = None
    if current_user.manager_id is not None:
        manager_user = await get_user_by_id(db, current_user.manager_id)
        manager_name = manager_user.full_name if manager_user else None

    supervisor_chain: list[User] = []
    seen_user_ids = {current_user.id}
    next_supervisor = manager_user
    while next_supervisor and next_supervisor.id not in seen_user_ids:
        supervisor_chain.append(next_supervisor)
        seen_user_ids.add(next_supervisor.id)
        if next_supervisor.manager_id is None:
            break
        next_supervisor = await get_user_by_id(db, next_supervisor.manager_id)

    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "title": current_user.title,
        "department": current_user.department,
        "role": current_user.role,
        "manager_id": current_user.manager_id,
        "manager_name": manager_name,
        "direct_reports": direct_reports,
        "supervisor_chain": supervisor_chain,
    }


@router.patch("/me/profile", response_model=UserResponse)
async def update_my_profile(
    payload: UserSelfUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Allow any authenticated user to update their own name, title, and department."""
    update = UserUpdate(**payload.model_dump(exclude_unset=True))
    return await update_user(db, current_user, update)


@router.post("/me/password", response_model=MessageResponse)
async def change_my_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    """Allow a user to change password by providing current password first."""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        )

    _validate_new_password(payload.new_password)

    current_user.hashed_password = get_password_hash(payload.new_password)
    current_user.has_changed_password = True
    db.add(current_user)
    await db.commit()

    # Audit: password changed
    await record_activity_events(db, [build_activity_event(
        activity_type="PASSWORD_CHANGED",
        visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
        tenant_id=current_user.tenant_id,
        actor_user=current_user,
        entity_type="user",
        entity_id=current_user.id,
        summary=f"{current_user.full_name} changed their password.",
        route="/users/me/password",
    )])

    return MessageResponse(message="Password updated successfully")


# ── Tenant Settings ──────────────────────────────────────────────────────────

@router.get("/tenant-settings", response_model=dict)
async def get_tenant_settings(
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get all settings for the current user's tenant."""
    from app.models.tenant_settings import TenantSettings
    result = await db.execute(
        select(TenantSettings).where(TenantSettings.tenant_id == current_user.tenant_id)
    )
    rows = result.scalars().all()
    return {row.key: row.value for row in rows}


@router.patch("/tenant-settings", response_model=dict)
async def update_tenant_settings(
    body: dict,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upsert one or more settings for the current user's tenant."""
    from app.models.tenant_settings import TenantSettings
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    now = datetime.now(timezone.utc)
    for key, value in body.items():
        str_value = str(value) if value is not None else None
        stmt = pg_insert(TenantSettings).values(
            tenant_id=current_user.tenant_id,
            key=key,
            value=str_value,
            created_at=now,
            updated_at=now,
        ).on_conflict_do_update(
            constraint="uq_tenant_settings_tenant_key",
            set_={"value": str_value, "updated_at": now},
        )
        await db.execute(stmt)
    await db.commit()
    return body


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Get a specific user by ID.
    Users can only view themselves unless they are admin.
    """
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Check access: user can view themselves; admin/platform_admin can view any user in their tenant
    if user_id != current_user.id:
        if current_user.role not in (UserRole.ADMIN, UserRole.PLATFORM_ADMIN):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        require_same_tenant(user.tenant_id, current_user)

    return user


@router.post("", response_model=UserCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_new_user(
    user_create: UserCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> dict:
    """
    Create a new user.
    - PLATFORM_ADMIN: can create users in any tenant (tenant_id must be provided in request body).
    - ADMIN: creates users in their own tenant (tenant_id from JWT, not request body).
    """
    from app.crud.user import get_user_by_email, get_user_by_username

    # Prevent ADMIN from escalating to PLATFORM_ADMIN role
    if current_user.role != UserRole.PLATFORM_ADMIN and user_create.role == UserRole.PLATFORM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a Platform Admin can create Platform Admin users",
        )

    if current_user.role == UserRole.PLATFORM_ADMIN:
        if user_create.role == UserRole.PLATFORM_ADMIN:
            # New PLATFORM_ADMIN users have no tenant
            user_create.tenant_id = None
        elif user_create.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tenant_id is required when creating a user as PLATFORM_ADMIN",
            )
    else:
        # ADMIN: always assign to their own tenant, ignore any tenant_id in body
        user_create.tenant_id = current_user.tenant_id

    existing = await get_user_by_email(db, user_create.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        )

    existing_username = await get_user_by_username(db, user_create.username)
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username is already taken",
        )

    # Password is always auto-generated — ignore any client-supplied value.
    user_create.password = None

    try:
        from app.services.email_verification import set_verification_token, send_verification_email
        from app.api.platform_settings import get_effective_smtp_config
        new_user, temp_password = await create_user(db, user_create)

        # Attach verification token
        token = set_verification_token(new_user)
        db.add(new_user)
        await db.commit()

        # Re-fetch with eager-loaded relationships so serialisation works
        new_user = await get_user_by_id(db, new_user.id)

        # Resolve SMTP config and tenant name while DB session is open
        smtp_config = await get_effective_smtp_config(db)
        tenant_name: str | None = None
        if new_user.tenant_id is not None:
            tenant = await get_tenant(db, new_user.tenant_id)
            tenant_name = tenant.name if tenant else None
        # Check if tenant has an active OAuth mailbox so the subject can be set correctly
        via_tenant_oauth = False
        if new_user.tenant_id is not None:
            from app.services.tenant_email_service import _get_active_oauth_mailbox
            via_tenant_oauth = await _get_active_oauth_mailbox(db, new_user.tenant_id) is not None
        background_tasks.add_task(send_verification_email, new_user, token, temp_password, smtp_config, tenant_name, new_user.tenant_id, via_tenant_oauth)

        activity_events: list[dict] = []
        if new_user.tenant_id is not None:
            if current_user.role == UserRole.PLATFORM_ADMIN and new_user.role == UserRole.ADMIN:
                tenant_name_for_log = tenant_name or f"tenant {new_user.tenant_id}"
                activity_events.append(
                    build_activity_event(
                        activity_type="TENANT_ADMIN_CREATED",
                        visibility_scope=PLATFORM_ADMIN_ACTIVITY_SCOPE,
                        tenant_id=new_user.tenant_id,
                        actor_user=current_user,
                        entity_type="tenant_admin",
                        entity_id=new_user.id,
                        summary=f"{current_user.full_name} added tenant admin {new_user.full_name} for {tenant_name}.",
                        route="/platform-admin",
                        route_params={"tenantId": new_user.tenant_id, "adminUserId": new_user.id},
                        metadata={"tenant_name": tenant_name, "user_role": new_user.role.value},
                    )
                )
            else:
                activity_events.append(
                    build_activity_event(
                        activity_type="USER_CREATED",
                        visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                        tenant_id=new_user.tenant_id,
                        actor_user=current_user,
                        entity_type="user",
                        entity_id=new_user.id,
                        summary=f"{current_user.full_name} created user {new_user.full_name}.",
                        route="/user-management",
                        route_params={"userId": new_user.id},
                        metadata={"role": new_user.role.value, "is_active": new_user.is_active},
                    )
                )

        await record_activity_events(db, activity_events)
        return {"user": new_user, "temporary_password": temp_password}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email or username already exists",
        )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user_endpoint(
    user_id: int,
    user_update: UserUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Update a user.
    - Admins can update any user.
    - Manager chain roles can update project access for employees in their reporting tree.
    """
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if current_user.role in (UserRole.ADMIN, UserRole.PLATFORM_ADMIN):
        require_same_tenant(user.tenant_id, current_user)
        if current_user.role == UserRole.ADMIN and user_update.role == UserRole.PLATFORM_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant admins cannot assign the PLATFORM_ADMIN role",
            )

        # Capture deactivation before updating (for outbound webhook)
        was_active = user.is_active
        previous_role = user.role
        previous_manager_id = user.manager_id
        previous_project_ids = sorted(user.project_ids or [])
        deactivated = (
            user.ingestion_employee_id is not None
            and user_update.is_active is False
            and was_active is True
        )

        try:
            updated_user = await update_user(db, user, user_update)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

        if deactivated:
            background_tasks.add_task(
                _send_outbound_webhook,
                tenant_id=current_user.tenant_id,
                event_type="user.deactivated",
                local_id=user.id,
                ingestion_id=user.ingestion_employee_id,
                changed_fields={"is_active": {"old": True, "new": False}},
                changed_by_name=current_user.full_name,
                session=db,
            )

        activity_events: list[dict] = []
        if updated_user.tenant_id is not None:
            tenant = await get_tenant(db, updated_user.tenant_id) if current_user.role == UserRole.PLATFORM_ADMIN else None
            tenant_name = tenant.name if tenant else None

            if previous_role != updated_user.role:
                if current_user.role == UserRole.PLATFORM_ADMIN and (
                    previous_role == UserRole.ADMIN or updated_user.role == UserRole.ADMIN
                ):
                    activity_events.append(
                        build_activity_event(
                            activity_type="TENANT_ADMIN_ROLE_CHANGED",
                            visibility_scope=PLATFORM_ADMIN_ACTIVITY_SCOPE,
                            tenant_id=updated_user.tenant_id,
                            actor_user=current_user,
                            entity_type="tenant_admin",
                            entity_id=updated_user.id,
                            summary=f"{current_user.full_name} changed {updated_user.full_name}'s role from {previous_role.value} to {updated_user.role.value}{f' for {tenant_name}' if tenant_name else ''}.",
                            route="/platform-admin",
                            route_params={"tenantId": updated_user.tenant_id, "adminUserId": updated_user.id},
                            metadata={"old_role": previous_role.value, "new_role": updated_user.role.value, "tenant_name": tenant_name},
                        )
                    )
                else:
                    activity_events.append(
                        build_activity_event(
                            activity_type="USER_ROLE_CHANGED",
                            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                            tenant_id=updated_user.tenant_id,
                            actor_user=current_user,
                            entity_type="user",
                            entity_id=updated_user.id,
                            summary=f"{current_user.full_name} changed {updated_user.full_name}'s role from {previous_role.value} to {updated_user.role.value}.",
                            route="/user-management",
                            route_params={"userId": updated_user.id},
                            metadata={"old_role": previous_role.value, "new_role": updated_user.role.value},
                        )
                    )

            if was_active != updated_user.is_active:
                if current_user.role == UserRole.PLATFORM_ADMIN and updated_user.role == UserRole.ADMIN:
                    activity_events.append(
                        build_activity_event(
                            activity_type="TENANT_ADMIN_STATUS_CHANGED",
                            visibility_scope=PLATFORM_ADMIN_ACTIVITY_SCOPE,
                            tenant_id=updated_user.tenant_id,
                            actor_user=current_user,
                            entity_type="tenant_admin",
                            entity_id=updated_user.id,
                            summary=f"{current_user.full_name} marked tenant admin {updated_user.full_name} as {'active' if updated_user.is_active else 'inactive'}{f' for {tenant_name}' if tenant_name else ''}.",
                            route="/platform-admin",
                            route_params={"tenantId": updated_user.tenant_id, "adminUserId": updated_user.id},
                            metadata={"old_is_active": was_active, "new_is_active": updated_user.is_active, "tenant_name": tenant_name},
                        )
                    )
                else:
                    activity_events.append(
                        build_activity_event(
                            activity_type="USER_STATUS_CHANGED",
                            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                            tenant_id=updated_user.tenant_id,
                            actor_user=current_user,
                            entity_type="user",
                            entity_id=updated_user.id,
                            summary=f"{current_user.full_name} marked {updated_user.full_name} as {'active' if updated_user.is_active else 'inactive'}.",
                            route="/user-management",
                            route_params={"userId": updated_user.id},
                            metadata={"old_is_active": was_active, "new_is_active": updated_user.is_active},
                        )
                    )

            if previous_manager_id != updated_user.manager_id:
                old_manager = await get_user_by_id(db, previous_manager_id) if previous_manager_id else None
                new_manager = await get_user_by_id(db, updated_user.manager_id) if updated_user.manager_id else None
                activity_events.append(
                    build_activity_event(
                        activity_type="USER_MANAGER_CHANGED",
                        visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                        tenant_id=updated_user.tenant_id,
                        actor_user=current_user,
                        entity_type="user",
                        entity_id=updated_user.id,
                        summary=f"{current_user.full_name} changed {updated_user.full_name}'s manager from {old_manager.full_name if old_manager else 'Unassigned'} to {new_manager.full_name if new_manager else 'Unassigned'}.",
                        route="/user-management",
                        route_params={"userId": updated_user.id},
                        metadata={
                            "old_manager_id": previous_manager_id,
                            "new_manager_id": updated_user.manager_id,
                            "old_manager_name": old_manager.full_name if old_manager else None,
                            "new_manager_name": new_manager.full_name if new_manager else None,
                        },
                    )
                )

            next_project_ids = sorted(updated_user.project_ids or [])
            if previous_project_ids != next_project_ids:
                activity_events.append(
                    build_activity_event(
                        activity_type="USER_PROJECT_ACCESS_CHANGED",
                        visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                        tenant_id=updated_user.tenant_id,
                        actor_user=current_user,
                        entity_type="user",
                        entity_id=updated_user.id,
                        summary=f"{current_user.full_name} updated project access for {updated_user.full_name}.",
                        route="/user-management",
                        route_params={"userId": updated_user.id},
                        metadata={"old_project_ids": previous_project_ids, "new_project_ids": next_project_ids},
                    )
                )

        await record_activity_events(db, activity_events)

        return updated_user

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Use /users/me/password to update your password",
        )

    if current_user.role not in MANAGER_CHAIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if user.role != UserRole.EMPLOYEE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Managers can only update employee project access",
        )

    managed_employee_ids = {employee.id for employee in await _get_managed_employees(db, current_user.id, current_user.tenant_id)}
    if user.id not in managed_employee_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    requested_update_fields = set(
        user_update.model_dump(exclude_unset=True).keys())
    if requested_update_fields - {"project_ids"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Managers can only update employee project assignments",
        )

    restricted_update = UserUpdate(project_ids=user_update.project_ids or [])
    previous_project_ids = sorted(user.project_ids or [])

    try:
        updated_user = await update_user(db, user, restricted_update)
        activity_events: list[dict] = []
        next_project_ids = sorted(updated_user.project_ids or [])
        if previous_project_ids != next_project_ids and updated_user.tenant_id is not None:
            activity_events.append(
                build_activity_event(
                    activity_type="USER_PROJECT_ACCESS_CHANGED",
                    visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                    tenant_id=updated_user.tenant_id,
                    actor_user=current_user,
                    entity_type="user",
                    entity_id=updated_user.id,
                    summary=f"{current_user.full_name} updated project access for {updated_user.full_name}.",
                    route="/user-management",
                    route_params={"userId": updated_user.id},
                    metadata={"old_project_ids": previous_project_ids, "new_project_ids": next_project_ids},
                )
            )
        await record_activity_events(db, activity_events)
        return updated_user
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_endpoint(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> None:
    """
    Delete a user (Admin or PLATFORM_ADMIN only).
    """
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    require_same_tenant(user.tenant_id, current_user)

    # Capture details before deletion
    deleted_user_name = user.full_name
    deleted_user_email = user.email
    deleted_user_role = user.role.value
    deleted_tenant_id = user.tenant_id

    success = await delete_user(db, user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Audit: user deleted
    await record_activity_events(db, [build_activity_event(
        activity_type="USER_DELETED",
        visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
        tenant_id=deleted_tenant_id,
        actor_user=current_user,
        entity_type="user",
        entity_id=user_id,
        summary=f"{current_user.full_name} deleted user {deleted_user_name} ({deleted_user_email}).",
        route="/user-management",
        metadata={"deleted_role": deleted_user_role, "deleted_email": deleted_user_email},
        severity="warning",
    )])


@router.post("/users/{user_id}/unlock-timesheet", response_model=dict)
async def unlock_user_timesheet(
    user_id: int,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Admin manually unlocks a user's timesheet."""
    result = await db.execute(select(User).where(
        (User.id == user_id) & (User.tenant_id == current_user.tenant_id)
    ))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    target_user.timesheet_locked = False
    target_user.timesheet_locked_reason = None
    await db.commit()
    return {"success": True, "user_id": user_id}
