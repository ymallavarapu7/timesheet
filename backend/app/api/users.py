import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, status, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas import UserResponse, UserCreate, UserUpdate, UserSelfUpdate, UserProfileResponse, ChangePasswordRequest, MessageResponse, UserCreateResponse, AdminPasswordResetRequest
from app.crud.user import get_user_by_id, create_user, update_user, delete_user, list_users
from app.core.permissions import get_user_permissions, shadow_check
from app.core.deps import get_current_user, get_tenant_db, require_role, require_same_tenant
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
logger = logging.getLogger(__name__)

MANAGER_CHAIN_ROLES = {UserRole.MANAGER}


async def _get_descendant_user_ids(
    db: AsyncSession, manager_id: int, tenant_id: int
) -> set[int]:
    """Walk the manager-chain to all transitive direct reports.

    BFS is tenant-scoped via User.tenant_id since EmployeeManagerAssignment
    has no tenant_id column.
    """
    descendant_ids: set[int] = set()
    frontier: set[int] = {manager_id}

    while frontier:
        result = await db.execute(
            select(EmployeeManagerAssignment.employee_id)
            .join(User, User.id == EmployeeManagerAssignment.employee_id)
            .where(EmployeeManagerAssignment.manager_id.in_(frontier))
            .where(User.tenant_id == tenant_id)
        )
        children = set(result.scalars().all())
        next_frontier = children - descendant_ids
        descendant_ids.update(next_frontier)
        frontier = next_frontier

    return descendant_ids


async def _get_managed_employees(db: AsyncSession, manager_id: int, tenant_id: int) -> list[User]:
    descendant_ids = await _get_descendant_user_ids(db, manager_id, tenant_id)
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
    descendant_ids = await _get_descendant_user_ids(db, manager_id, tenant_id)
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


@router.get("/assignable", response_model=list[UserResponse])
async def list_assignable_users(
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role(
        "MANAGER", "VIEWER", "ADMIN", "PLATFORM_ADMIN"
    )),
) -> list[User]:
    """Full tenant employee list for assignment dropdowns (e.g. ingestion review panel)."""
    return await list_users(db, tenant_id=current_user.tenant_id, skip=0, limit=1000)


@router.get("", response_model=list[UserResponse])
async def list_all_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
) -> list[User]:
    """List users; scope depends on role (platform/tenant/manager-chain)."""
    old_decision = current_user.role in {
        UserRole.PLATFORM_ADMIN,
        UserRole.ADMIN,
        UserRole.MANAGER,
        UserRole.VIEWER,
    }
    await shadow_check(
        db,
        current_user,
        "user.read",
        old_decision=old_decision,
        context="GET /users",
    )

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


@router.get("/me/permissions")
async def get_my_permissions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    perms = await get_user_permissions(db, current_user)
    return {"permissions": sorted(perms)}


@router.get("/me/profile", response_model=UserProfileResponse)
async def get_my_profile(
    db: AsyncSession = Depends(get_tenant_db),
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
        "username": current_user.username,
        "full_name": current_user.full_name,
        "title": current_user.title,
        "department": current_user.department,
        "timezone": current_user.timezone,
        "role": current_user.role,
        "manager_id": current_user.manager_id,
        "manager_name": manager_name,
        "direct_reports": direct_reports,
        "supervisor_chain": supervisor_chain,
    }


@router.patch("/me/profile", response_model=UserResponse)
async def update_my_profile(
    payload: UserSelfUpdate,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Self-update profile. Regular users can edit name/title/timezone/username.
    Platform admins can also edit their email."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy import select as sa_select

    data = payload.model_dump(exclude_unset=True)

    # Only platform admins can change their own email.
    if "email" in data and current_user.role != UserRole.PLATFORM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform administrators can change their own email.",
        )

    # Pre-check username uniqueness to surface a friendly error instead of 500.
    if "username" in data and data["username"] is not None:
        next_username = data["username"].strip().lower()
        if not next_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username cannot be blank.",
            )
        if next_username != current_user.username:
            taken = await db.execute(
                sa_select(User.id).where(User.username == next_username)
            )
            if taken.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="That username is already taken.",
                )
        data["username"] = next_username

    # Pre-check email uniqueness for platform admin self-edits.
    if "email" in data and data["email"] is not None:
        next_email = data["email"].strip().lower()
        if next_email != current_user.email:
            taken = await db.execute(
                sa_select(User.id).where(User.email == next_email)
            )
            if taken.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="That email is already in use.",
                )
        data["email"] = next_email

    update = UserUpdate(**data)
    try:
        return await update_user(db, current_user, update)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username or email is already in use.",
        )


@router.post("/me/password", response_model=MessageResponse)
async def change_my_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(get_tenant_db),
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
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Get every setting for the tenant; falls back to catalog defaults."""
    from app.core.tenant_settings import get_all_settings

    if current_user.tenant_id is None:
        return {}
    return await get_all_settings(db, current_user.tenant_id)


@router.get("/tenant-settings/catalog", response_model=list)
async def get_tenant_settings_catalog(
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_tenant_db),
) -> list:
    """Return the full setting-definition catalog used by the admin settings form."""
    from app.core.tenant_settings import get_catalog

    return await get_catalog(db)


@router.get("/tenant-settings/public", response_model=dict)
async def get_public_tenant_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Whitelisted tenant settings readable by any authenticated user."""
    from app.core.tenant_settings import get_public_settings

    if current_user.tenant_id is None:
        return {}
    return await get_public_settings(db, current_user.tenant_id)


@router.patch("/tenant-settings", response_model=dict)
async def update_tenant_settings(
    body: dict,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Upsert tenant settings; validated against the catalog (422 on failure)."""
    from app.core.tenant_settings import set_setting

    await shadow_check(
        db,
        current_user,
        "tenant.settings.update",
        old_decision=True,
        context="PATCH /users/tenant-settings",
    )

    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PLATFORM_ADMIN has no tenant-scoped settings",
        )

    result: dict = {}
    for key, value in body.items():
        try:
            result[key] = await set_setting(
                db,
                current_user.tenant_id,
                key,
                value,
                actor_id=current_user.id,
            )
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown setting key: {key!r}",
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )
    await db.commit()
    return result


class BulkDeleteUsersRequest(PydanticBaseModel):
    user_ids: list[int]


@router.post("/bulk-delete")
async def bulk_delete_users(
    body: BulkDeleteUsersRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> dict:
    deleted = 0
    for user_id in body.user_ids:
        user = await get_user_by_id(db, user_id)
        if not user:
            continue
        if user.tenant_id != current_user.tenant_id and current_user.role != UserRole.PLATFORM_ADMIN:
            continue
        if user.id == current_user.id:
            continue
        success = await delete_user(db, user_id)
        if success:
            deleted += 1
    return {"deleted": deleted}


@router.post("/{user_id}/reset-password", response_model=MessageResponse)
async def reset_user_password(
    user_id: int,
    payload: AdminPasswordResetRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> MessageResponse:
    """Admin resets a user's password. User will be prompted to change it on next login."""
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.tenant_id != current_user.tenant_id and current_user.role != UserRole.PLATFORM_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use the change password page to update your own password")

    _validate_new_password(payload.new_password)

    user.hashed_password = get_password_hash(payload.new_password)
    user.has_changed_password = False
    db.add(user)
    await db.commit()

    return MessageResponse(message="Password reset successfully. User will be prompted to change it on next login.")


@router.post("/{user_id}/resend-verification", response_model=MessageResponse)
async def resend_verification_email_endpoint(
    user_id: int,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> MessageResponse:
    """Admin resends a verification email; rotates temp password + token."""
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.tenant_id != current_user.tenant_id and current_user.role != UserRole.PLATFORM_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already verified. Use Reset Password instead.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot send verification: user account is inactive",
        )
    if user.is_external:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot send verification: external users do not log in.",
        )
    # Refuse the synthesized @local.invalid placeholder used when no email was set.
    if (user.email or "").lower().endswith("@local.invalid"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot send verification: user has no real email address. Add one first.",
        )

    from app.crud.user import _generate_default_password
    from app.services.email_verification import set_verification_token, send_verification_email

    new_temp_password = _generate_default_password()
    user.hashed_password = get_password_hash(new_temp_password)
    user.has_changed_password = False
    token = set_verification_token(user)
    db.add(user)
    await db.commit()

    tenant_name = None
    if user.tenant_id is not None:
        from app.crud.tenant import get_tenant
        tenant = await get_tenant(db, user.tenant_id)
        tenant_name = tenant.name if tenant else None

    await send_verification_email(
        user,
        token,
        temporary_password=new_temp_password,
        tenant_name=tenant_name,
        tenant_id=user.tenant_id,
        resend=True,
    )

    return MessageResponse(message=f"Verification email resent to {user.email}.")


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Get a user by ID. Users can only view themselves unless they are admin."""
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

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
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> dict:
    """Create a user. PLATFORM_ADMIN passes tenant_id; ADMIN uses their own."""
    from app.crud.user import get_user_by_email, get_user_by_username

    if current_user.role != UserRole.PLATFORM_ADMIN and user_create.role == UserRole.PLATFORM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a Platform Admin can create Platform Admin users",
        )

    if current_user.role == UserRole.PLATFORM_ADMIN:
        if user_create.role == UserRole.PLATFORM_ADMIN:
            user_create.tenant_id = None
        elif user_create.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tenant_id is required when creating a user as PLATFORM_ADMIN",
            )
    else:
        user_create.tenant_id = current_user.tenant_id

    if user_create.email:
        existing = await get_user_by_email(db, user_create.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email already exists",
            )

    if user_create.username:
        existing_username = await get_user_by_username(db, user_create.username)
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username is already taken",
            )

    user_create.password = None  # always auto-generated

    try:
        from app.services.email_verification import set_verification_token, send_verification_email
        from app.api.platform_settings import get_effective_smtp_config
        new_user, temp_password = await create_user(db, user_create)

        # Verification email only goes to internal+active users with a real email.
        provided_real_email = bool(user_create.email)
        send_verification = (
            new_user.is_active
            and not new_user.is_external
            and provided_real_email
        )

        token: str | None = None
        if send_verification:
            token = set_verification_token(new_user)
            db.add(new_user)
        await db.commit()

        # Re-fetch with eager-loaded relationships so serialisation works.
        new_user = await get_user_by_id(db, new_user.id)

        smtp_config = await get_effective_smtp_config(db)
        tenant_name: str | None = None
        if new_user.tenant_id is not None:
            tenant = await get_tenant(db, new_user.tenant_id)
            tenant_name = tenant.name if tenant else None
        via_tenant_oauth = False
        if new_user.tenant_id is not None:
            from app.services.tenant_email_service import _get_active_oauth_mailbox
            via_tenant_oauth = await _get_active_oauth_mailbox(db, new_user.tenant_id) is not None

        if send_verification and token is not None:
            background_tasks.add_task(
                send_verification_email,
                new_user, token, temp_password, smtp_config, tenant_name,
                new_user.tenant_id, via_tenant_oauth,
            )
        else:
            reason = (
                "external user" if new_user.is_external
                else ("inactive user" if not new_user.is_active else "no email on file")
            )
            logger.info(
                "verification_email_skipped: user=%s reason=%s",
                new_user.email, reason,
            )

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
        return {
            "user": new_user,
            "temporary_password": temp_password,
            "verification_email_sent": send_verification,
        }
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
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Update a user. Admins update any user; managers may set project access for reports."""
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

        was_active = user.is_active
        previous_role = user.role
        previous_manager_id = user.manager_id
        previous_project_ids = sorted(user.project_ids or [])
        deactivated = (
            user.ingestion_employee_id is not None
            and user_update.is_active is False
            and was_active is True
        )

        from sqlalchemy.exc import IntegrityError
        try:
            updated_user = await update_user(db, user, user_update)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That username or email is already in use.",
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
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> None:
    """Delete a user (Admin or PLATFORM_ADMIN only)."""
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    require_same_tenant(user.tenant_id, current_user)

    deleted_user_name = user.full_name
    deleted_user_email = user.email
    deleted_user_role = user.role.value
    deleted_tenant_id = user.tenant_id

    success = await delete_user(db, user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

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


MAX_ALIASES_PER_USER = 2


class EmailAliasRead(PydanticBaseModel):
    id: int
    email: str
    created_at: datetime


class EmailAliasCreateRequest(PydanticBaseModel):
    email: str


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


@router.get("/{user_id}/email-aliases", response_model=list[EmailAliasRead])
async def list_email_aliases(
    user_id: int,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
) -> list[EmailAliasRead]:
    """Aliases on a user. Self or admin only; cross-tenant access denied."""
    from app.models.user_email_alias import UserEmailAlias

    target = await get_user_by_id(db, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user_id != current_user.id:
        if current_user.role not in (UserRole.ADMIN, UserRole.PLATFORM_ADMIN):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        require_same_tenant(target.tenant_id, current_user)

    result = await db.execute(
        select(UserEmailAlias)
        .where(UserEmailAlias.user_id == user_id)
        .order_by(UserEmailAlias.created_at.asc())
    )
    return [
        EmailAliasRead(id=row.id, email=row.email, created_at=row.created_at)
        for row in result.scalars().all()
    ]


@router.post(
    "/{user_id}/email-aliases",
    response_model=EmailAliasRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_email_alias(
    user_id: int,
    body: EmailAliasCreateRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> EmailAliasRead:
    """Add an alias email (admin-only). Capped at MAX_ALIASES_PER_USER."""
    from app.crud.user import get_user_by_email
    from app.models.user_email_alias import UserEmailAlias

    target = await get_user_by_id(db, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    require_same_tenant(target.tenant_id, current_user)

    normalized = _normalize_email(body.email)
    if not normalized or "@" not in normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email address")

    if normalized == (target.email or "").lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Alias matches the user's primary email",
        )

    from sqlalchemy import func as sa_func
    existing_count = (await db.execute(
        select(sa_func.count(UserEmailAlias.id))
        .where(UserEmailAlias.user_id == user_id)
    )).scalar_one()
    if existing_count >= MAX_ALIASES_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"At most {MAX_ALIASES_PER_USER} alias emails per user",
        )

    # Refuse if any other user already owns this address (primary or alias).
    existing_user = await get_user_by_email(db, normalized)
    if existing_user is not None and existing_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already in use by another user",
        )

    alias = UserEmailAlias(user_id=user_id, email=normalized)
    db.add(alias)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already in use",
        )
    await db.refresh(alias)
    return EmailAliasRead(id=alias.id, email=alias.email, created_at=alias.created_at)


@router.delete(
    "/{user_id}/email-aliases/{alias_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_email_alias(
    user_id: int,
    alias_id: int,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> None:
    """Remove an alias (admin-only)."""
    from app.models.user_email_alias import UserEmailAlias

    target = await get_user_by_id(db, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    require_same_tenant(target.tenant_id, current_user)

    result = await db.execute(
        select(UserEmailAlias).where(
            (UserEmailAlias.id == alias_id) & (UserEmailAlias.user_id == user_id)
        )
    )
    alias = result.scalar_one_or_none()
    if not alias:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alias not found")
    await db.delete(alias)
    await db.commit()


@router.post("/import/preview", response_model=dict)
async def import_users_preview(
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Parse an uploaded CSV/XLSX file and return headers + preview rows.

    No DB writes. The frontend uses this to render the column-mapping step.
    """
    from app.services.user_import import parse_file

    content = await file.read()
    try:
        headers, rows = parse_file(file.filename or "upload.csv", content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    preview_rows = [
        {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
        for row in rows[:5]
    ]

    return {
        "headers": headers,
        "preview_rows": preview_rows,
        "total_rows": len(rows),
    }


class ImportCommitBody(PydanticBaseModel):
    mapping: dict[str, str]
    rows: list[list[str]]
    headers: list[str]
    user_type: str = "external"          # "external" | "internal"
    default_client_id: int | None = None
    default_project_id: int | None = None
    default_manager_id: int | None = None


@router.post("/import/commit", response_model=dict)
async def import_users_commit(
    body: ImportCommitBody,
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Commit a mapped + validated import batch.

    Each row is created independently; per-row errors are collected and
    returned without aborting the remaining rows.

    Batch-level defaults (user_type, default_client_id, default_project_id,
    default_manager_id) apply to every row unless that row's mapped columns
    provide a value. Per-row values always win.
    """
    from app.services.user_import import (
        apply_mapping, validate_row,
        resolve_client_id, resolve_project_id, resolve_manager_id,
    )
    from app.schemas import UserCreate
    from app.crud.user import create_user as crud_create_user, get_user_by_email
    from app.models.user_email_alias import UserEmailAlias
    from app.models.user import UserRole as _UserRole

    tenant_id = current_user.tenant_id
    is_external_default = body.user_type != "internal"

    existing_emails_result = await db.execute(
        select(User.email).where(User.tenant_id == tenant_id)
    )
    existing_emails: set[str] = {r.lower() for r in existing_emails_result.scalars().all() if r}

    records = apply_mapping(body.headers, body.rows, body.mapping)

    created: list[dict] = []
    skipped: list[dict] = []
    seen_emails: set[str] = set()

    for idx, record in enumerate(records):
        validated = validate_row(record, idx + 1, existing_emails, seen_emails)
        if validated["errors"]:
            skipped.append({"row": idx + 1, "reason": "; ".join(validated["errors"])})
            continue

        full_name = validated["full_name"]
        if not full_name:
            skipped.append({"row": idx + 1, "reason": "Full name is required"})
            continue

        row_client = await resolve_client_id(db, validated["client"], tenant_id) if (tenant_id and validated["client"]) else None
        row_project = await resolve_project_id(db, validated["project"], tenant_id) if (tenant_id and validated["project"]) else None
        row_manager = await resolve_manager_id(db, validated["manager"], tenant_id) if (tenant_id and validated["manager"]) else None

        client_id = row_client if row_client is not None else body.default_client_id
        project_id = row_project if row_project is not None else body.default_project_id
        manager_id = row_manager if row_manager is not None else body.default_manager_id

        try:
            user_create = UserCreate(
                full_name=full_name,
                is_external=is_external_default,
                email=validated["email"] or None,
                title=validated["title"] or None,
                department=validated["department"] or None,
                role=_UserRole(validated["role"]),
                is_active=validated["is_active"],
                manager_id=manager_id,
                project_ids=[project_id] if project_id else [],
                default_client_id=client_id,
                phones=validated["phones"],
                tenant_id=tenant_id,
            )
            user, _ = await crud_create_user(db, user_create)
        except Exception as exc:
            skipped.append({"row": idx + 1, "reason": str(exc)})
            continue

        for alias_email in validated["extra_emails"]:
            existing_owner = await get_user_by_email(db, alias_email)
            if existing_owner is None:
                db.add(UserEmailAlias(user_id=user.id, email=alias_email))
        try:
            await db.commit()
        except Exception:
            await db.rollback()

        if validated["email"]:
            existing_emails.add(validated["email"])

        created.append({
            "row": idx + 1,
            "user_id": user.id,
            "full_name": user.full_name,
            "warnings": validated["warnings"],
        })

    return {
        "created": len(created),
        "skipped": len(skipped),
        "details": {"created": created, "skipped": skipped},
    }


# ---------------------------------------------------------------------------
# Export endpoints (ADMIN only)
# ---------------------------------------------------------------------------

def _export_response(
    content: bytes,
    mime: str,
    filename: str,
) -> Response:
    return Response(
        content=content,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/users")
async def export_users_endpoint(
    fmt: str = Query("csv", regex="^(csv|xlsx)$"),
    user_type: str = Query("all", regex="^(all|internal|external)$"),
    role: str | None = Query(None),
    status_filter: str = Query("all", regex="^(all|active|inactive)$"),
    client_id: int | None = Query(None),
    department: str | None = Query(None),
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    from app.services.admin_export import export_users, serialize

    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant scope required")

    headers, rows = await export_users(
        db,
        current_user.tenant_id,
        user_type=user_type,
        role=role,
        status_filter=status_filter,
        client_id=client_id,
        department=department,
    )
    content, mime, ext = serialize(headers, rows, fmt, sheet_name="Users")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"users-{stamp}.{ext}"
    return _export_response(content, mime, filename)


@router.get("/export/clients")
async def export_clients_endpoint(
    fmt: str = Query("csv", regex="^(csv|xlsx)$"),
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    from app.services.admin_export import export_clients, serialize

    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant scope required")

    headers, rows = await export_clients(db, current_user.tenant_id)
    content, mime, ext = serialize(headers, rows, fmt, sheet_name="Clients")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"clients-{stamp}.{ext}"
    return _export_response(content, mime, filename)


@router.get("/export/timesheets")
async def export_timesheets_endpoint(
    period_start: date = Query(...),
    period_end: date = Query(...),
    fmt: str = Query("csv", regex="^(csv|xlsx)$"),
    user_type: str = Query("all", regex="^(all|internal|external)$"),
    user_id: int | None = Query(None),
    client_id: int | None = Query(None),
    project_id: int | None = Query(None),
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    from app.services.admin_export import export_approved_timesheets, serialize

    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant scope required")
    if period_end < period_start:
        raise HTTPException(status_code=400, detail="period_end must be on or after period_start")

    headers, rows = await export_approved_timesheets(
        db,
        current_user.tenant_id,
        period_start=period_start,
        period_end=period_end,
        user_type=user_type,
        user_id=user_id,
        client_id=client_id,
        project_id=project_id,
    )
    content, mime, ext = serialize(headers, rows, fmt, sheet_name="Timesheets")
    filename = f"approved-timesheets-{period_start.isoformat()}-to-{period_end.isoformat()}.{ext}"
    return _export_response(content, mime, filename)


@router.post("/users/{user_id}/unlock-timesheet", response_model=dict)
async def unlock_user_timesheet(
    user_id: int,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_tenant_db),
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
