from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.schemas import LoginRequest, TokenResponse, UserResponse, UserCreate, ChangePasswordRequest, PasswordChangeResponse, RefreshRequest, VerifyEmailRequest, VerifyEmailResponse, ResendVerificationRequest, MessageResponse, RoleSwitchRequest, RoleHandoffIssueResponse, RoleHandoffExchangeRequest
from app.crud.user import get_user_by_email, create_user
from sqlalchemy import select, update
from app.core.security import verify_password, create_access_token, create_refresh_token, get_password_hash
from app.core.deps import get_current_user
from app.models.user import User, UserRole
from app.models.refresh_token import RefreshToken
from app.core.rate_limit import limiter
from app.services.activity import (
    TENANT_ADMIN_ACTIVITY_SCOPE,
    build_activity_event,
    record_activity_events,
)

DEFAULT_MAX_FAILED_ATTEMPTS = 5
DEFAULT_LOCKOUT_DURATION_MINUTES = 15


async def _resolve_tenant_slug(db: AsyncSession, tenant_id: int | None) -> str | None:
    """Look up the slug for a tenant_id; None for platform admins."""
    if tenant_id is None:
        return None
    from sqlalchemy import text
    row = (await db.execute(
        text("SELECT slug FROM tenants WHERE id = :tid"),
        {"tid": tenant_id},
    )).first()
    return row[0] if row else None


def _build_token_payload(
    *,
    user_id: int,
    tenant_id: int | None,
    can_review: bool,
    realm: str,
    tenant_slug: str | None,
    active_role: str | None = None,
) -> dict:
    """Assemble the JWT payload for access and refresh tokens.

    Single source of truth so login + refresh agree on claim shape.
    ``active_role`` is the per-token role for multi-role users; lets
    two tabs of the same user act as different roles independently.
    """
    payload = {
        "sub": str(user_id),
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "realm": realm,
        "can_review": can_review,
    }
    if active_role is not None:
        payload["active_role"] = active_role
    return payload


async def _lockout_policy(db: AsyncSession, tenant_id: int | None) -> tuple[int, int]:
    """(max_attempts, lockout_minutes) — per tenant with defaults."""
    if tenant_id is None:
        return DEFAULT_MAX_FAILED_ATTEMPTS, DEFAULT_LOCKOUT_DURATION_MINUTES
    from app.models.tenant_settings import TenantSettings
    from sqlalchemy import select as _select
    result = await db.execute(
        _select(TenantSettings.key, TenantSettings.value).where(
            TenantSettings.tenant_id == tenant_id,
            TenantSettings.key.in_(("max_failed_login_attempts", "lockout_duration_minutes")),
        )
    )
    rows = {row[0]: row[1] for row in result.all()}
    def _i(v, d):
        try:
            n = int(str(v).strip())
            return max(1, n)
        except Exception:
            return d
    return (
        _i(rows.get("max_failed_login_attempts"), DEFAULT_MAX_FAILED_ATTEMPTS),
        _i(rows.get("lockout_duration_minutes"), DEFAULT_LOCKOUT_DURATION_MINUTES),
    )

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_create: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Register a new user (Admin only).
    """
    # Check if admin or platform admin
    if current_user.role not in (UserRole.ADMIN, UserRole.PLATFORM_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can register new users",
        )

    # Prevent ADMIN from escalating to PLATFORM_ADMIN role
    if current_user.role != UserRole.PLATFORM_ADMIN and user_create.role == UserRole.PLATFORM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a Platform Admin can create Platform Admin users",
        )

    # Determine tenant_id for the new user
    if current_user.role == UserRole.PLATFORM_ADMIN:
        if user_create.role == UserRole.PLATFORM_ADMIN:
            # New PLATFORM_ADMIN users have no tenant
            tenant_id = None
        elif not user_create.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tenant_id is required when creating users as platform admin",
            )
        else:
            tenant_id = user_create.tenant_id
    else:
        # Tenant ADMIN can only create users in their own tenant
        tenant_id = current_user.tenant_id

    # Check if user already exists
    existing_user = await get_user_by_email(db, user_create.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Inject the resolved tenant_id
    user_create.tenant_id = tenant_id

    # Enforce password policy if a password is explicitly provided
    if user_create.password:
        from app.api.users import _validate_new_password
        _validate_new_password(user_create.password)

    # Create user
    new_user, _temp_password = await create_user(db, user_create)
    return new_user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    login_request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Login with email + password; return JWT tokens.

    Account locks for 15 min after 5 consecutive failed attempts.
    Platform admins authenticate against the control plane first.
    """
    from app.db_control import AsyncControlSessionLocal
    from app.models.control import PlatformAdmin
    async with AsyncControlSessionLocal() as control_db:
        pa_row = (await control_db.execute(
            select(PlatformAdmin).where(PlatformAdmin.email == login_request.email)
        )).scalar_one_or_none()

    if pa_row is not None:
        if not verify_password(login_request.password, pa_row.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        if not pa_row.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )
        pa_payload = _build_token_payload(
            user_id=pa_row.id,
            tenant_id=None,
            can_review=False,
            realm="platform",
            tenant_slug=None,
        )
        pa_access = create_access_token(pa_payload)
        pa_refresh, pa_jti, pa_expires = create_refresh_token(pa_payload)
        # Platform-admin refresh tokens are not persisted yet; refresh
        # works from the JWT signature alone.
        return {
            "access_token": pa_access,
            "refresh_token": pa_refresh,
            "token_type": "bearer",
            "user": {
                "id": pa_row.id,
                "tenant_id": None,
                "email": pa_row.email,
                "username": pa_row.username,
                "full_name": pa_row.full_name,
                "title": None,
                "department": None,
                "timezone": "UTC",
                "role": UserRole.PLATFORM_ADMIN,
                "is_active": pa_row.is_active,
                "manager_id": None,
                "project_ids": [],
                "default_client_id": None,
                "has_changed_password": pa_row.has_changed_password,
                "email_verified": pa_row.email_verified,
                "can_review": False,
                "is_external": False,
                "created_at": pa_row.created_at,
                "updated_at": pa_row.updated_at,
            },
        }

    # Look up by email in shared DB, then re-fetch from the tenant DB
    # if the tenant is isolated (source of truth for password + lockout).
    user = await get_user_by_email(db, login_request.email)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    tenant_slug = await _resolve_tenant_slug(db, user.tenant_id)
    use_tenant_db = bool(tenant_slug)

    if use_tenant_db:
        from app.db_tenant import tenant_session
        try:
            async with tenant_session(tenant_slug) as tenant_db:
                refreshed = await get_user_by_email(tenant_db, login_request.email)
            if refreshed is not None:
                user = refreshed
            else:
                # Tenant DB doesn't know this email; fall back to shared.
                use_tenant_db = False
        except (LookupError, ValueError):
            use_tenant_db = False

    # Check if account is locked
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        remaining = int((user.locked_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is locked due to too many failed attempts. Try again in {remaining} minute(s).",
        )

    # Verify password
    if not verify_password(login_request.password, user.hashed_password):
        max_attempts, lockout_minutes = await _lockout_policy(db, user.tenant_id)
        if use_tenant_db:
            from app.db_tenant import tenant_session
            async with tenant_session(tenant_slug) as tenant_db:
                target = (await tenant_db.execute(
                    select(User).where(User.id == user.id)
                )).scalar_one()
                target.failed_login_attempts = (target.failed_login_attempts or 0) + 1
                locked = target.failed_login_attempts >= max_attempts
                if locked:
                    target.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)
                tenant_db.add(target)
                await tenant_db.commit()
                user = target
        else:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            locked = user.failed_login_attempts >= max_attempts
            if locked:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)
            db.add(user)
            await db.commit()

        # Audit: failed login
        await record_activity_events(db, [build_activity_event(
            activity_type="LOGIN_FAILED",
            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
            tenant_id=user.tenant_id,
            actor_user=user,
            entity_type="user",
            entity_id=user.id,
            summary=f"Failed login attempt for {user.email} (attempt {user.failed_login_attempts}){' — account locked' if locked else ''}.",
            route="/auth/login",
            metadata={"attempt": user.failed_login_attempts, "locked": locked},
            severity="warning" if not locked else "critical",
        )])

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="EMAIL_NOT_VERIFIED",
        )

    realm = "platform" if user.role == UserRole.PLATFORM_ADMIN else "tenant"
    token_payload = _build_token_payload(
        user_id=user.id,
        tenant_id=user.tenant_id,
        can_review=user.can_review,
        realm=realm,
        tenant_slug=tenant_slug,
    )
    access_token = create_access_token(token_payload)
    refresh_token, jti, expires_at = create_refresh_token(token_payload)

    now = datetime.now(timezone.utc)
    previous_last_login_at = user.last_login_at

    if use_tenant_db:
        from app.db_tenant import tenant_session
        async with tenant_session(tenant_slug) as tenant_db:
            target = (await tenant_db.execute(
                select(User).where(User.id == user.id)
            )).scalar_one()
            target.failed_login_attempts = 0
            target.locked_until = None
            target.last_login_at = now
            tenant_db.add(target)
            tenant_db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=expires_at))
            await tenant_db.commit()
            await record_activity_events(tenant_db, [build_activity_event(
                activity_type="LOGIN_SUCCESS",
                visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                tenant_id=user.tenant_id,
                actor_user=target,
                entity_type="user",
                entity_id=user.id,
                summary=f"{target.full_name} logged in.",
                route="/auth/login",
            )])
    else:
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        db.add(user)
        db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=expires_at))
        await db.commit()
        await record_activity_events(db, [build_activity_event(
            activity_type="LOGIN_SUCCESS",
            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
            tenant_id=user.tenant_id,
            actor_user=user,
            entity_type="user",
            entity_id=user.id,
            summary=f"{user.full_name} logged in.",
            route="/auth/login",
        )])

    # Re-fetch with eager loads so response serialization doesn't hit
    # expired attributes after the commits above.
    if tenant_slug:
        from app.db_tenant import tenant_session
        try:
            async with tenant_session(tenant_slug) as tenant_db:
                refreshed = await get_user_by_email(tenant_db, user.email)
            if refreshed is not None:
                user = refreshed
            else:
                user = await get_user_by_email(db, user.email)
        except (LookupError, ValueError):
            user = await get_user_by_email(db, user.email)
    else:
        user = await get_user_by_email(db, user.email)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user,
        "previous_last_login_at": (
            previous_last_login_at.isoformat() if previous_last_login_at else None
        ),
    }


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
async def refresh_token(
    request: Request,
    body: RefreshRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Refresh access token; single-use rotation with FOR UPDATE row lock."""
    from app.core.security import decode_token
    from app.crud.user import get_user_by_id
    from app.db_tenant import tenant_session

    token = body.refresh_token if body else None
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token provided")

    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user_id = payload.get("sub")
    jti = payload.get("jti")
    token_tenant_slug = payload.get("tenant_slug")
    token_active_role = payload.get("active_role")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    # Refresh tokens for an isolated tenant live in the per-tenant DB,
    # so check/revoke/insert all happen in one transaction.
    use_tenant_db = bool(token_tenant_slug)

    async def _do_refresh(session: AsyncSession) -> tuple[User, str, str, datetime]:
        """Lock + revoke + insert on the given session, atomically."""
        if jti:
            stored = (await session.execute(
                select(RefreshToken)
                .where(RefreshToken.jti == jti)
                .with_for_update()
            )).scalars().first()
            if not stored or stored.revoked:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh token has been revoked",
                )
            stored.revoked = True
            session.add(stored)

        user = await get_user_by_id(session, int(user_id))
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )

        realm = "platform" if user.role == UserRole.PLATFORM_ADMIN else "tenant"
        # Carry forward active_role so multi-role users don't get
        # downgraded; re-validated against user.roles on next request.
        token_payload = _build_token_payload(
            user_id=user.id,
            tenant_id=user.tenant_id,
            can_review=user.can_review,
            realm=realm,
            tenant_slug=token_tenant_slug,
            active_role=token_active_role,
        )
        new_access = create_access_token(token_payload)
        new_refresh, new_jti, new_expires = create_refresh_token(token_payload)

        session.add(RefreshToken(user_id=user.id, jti=new_jti, expires_at=new_expires))
        await session.commit()
        return user, new_access, new_refresh, new_expires

    if use_tenant_db:
        try:
            async with tenant_session(token_tenant_slug) as tenant_db:
                user, access_token, new_refresh_token, _ = await _do_refresh(tenant_db)
        except (LookupError, ValueError):
            user, access_token, new_refresh_token, _ = await _do_refresh(db)
    else:
        user, access_token, new_refresh_token, _ = await _do_refresh(db)

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "user": user,
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
) -> User:
    """Return the current authenticated user."""
    return current_user


@router.post("/change-password", response_model=PasswordChangeResponse)
async def change_password(
    request: Request,
    change_password_request: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Change password and revoke all of the user's refresh tokens."""
    if not verify_password(change_password_request.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    from app.core.password_policy import validate_password
    error = validate_password(change_password_request.new_password)
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    new_hash = get_password_hash(change_password_request.new_password)

    auth_hdr = request.headers.get("authorization", "")
    token_tenant_slug: str | None = None
    if auth_hdr.lower().startswith("bearer "):
        from app.core.security import decode_token
        payload = decode_token(auth_hdr[7:])
        if payload:
            token_tenant_slug = payload.get("tenant_slug")

    if token_tenant_slug:
        from app.db_tenant import tenant_session
        async with tenant_session(token_tenant_slug) as tenant_db:
            target = (await tenant_db.execute(
                select(User).where(User.id == current_user.id)
            )).scalar_one()
            target.hashed_password = new_hash
            target.has_changed_password = True
            tenant_db.add(target)
            await tenant_db.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.user_id == current_user.id,
                    RefreshToken.revoked == False,  # noqa: E712
                )
                .values(revoked=True)
            )
            await tenant_db.commit()
            await record_activity_events(tenant_db, [build_activity_event(
                activity_type="PASSWORD_CHANGED",
                visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                tenant_id=current_user.tenant_id,
                actor_user=target,
                entity_type="user",
                entity_id=target.id,
                summary=f"{target.full_name} changed their password.",
                route="/auth/change-password",
            )])
    else:
        current_user.hashed_password = new_hash
        current_user.has_changed_password = True
        db.add(current_user)
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == current_user.id,
                RefreshToken.revoked == False,  # noqa: E712
            )
            .values(revoked=True)
        )
        await db.commit()
        await record_activity_events(db, [build_activity_event(
            activity_type="PASSWORD_CHANGED",
            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
            tenant_id=current_user.tenant_id,
            actor_user=current_user,
            entity_type="user",
            entity_id=current_user.id,
            summary=f"{current_user.full_name} changed their password.",
            route="/auth/change-password",
        )])

    return {
        "success": True,
        "message": "Password changed successfully",
    }


@router.post("/logout")
async def logout(
    body: RefreshRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Revoke the current refresh token (logout)."""
    from app.core.security import decode_token

    token = body.refresh_token if body else None
    if token:
        payload = decode_token(token)
        jti = payload.get("jti") if payload else None
        if jti:
            result = await db.execute(
                select(RefreshToken).where(
                    RefreshToken.jti == jti,
                    RefreshToken.user_id == current_user.id,
                )
            )
            stored = result.scalars().first()
            if stored:
                stored.revoked = True
                db.add(stored)
                await db.commit()

    return {"message": "Logged out successfully"}


@router.post("/revoke-all-tokens")
async def revoke_all_user_tokens(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Revoke all refresh tokens for the current user (force logout all sessions)."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == current_user.id, RefreshToken.revoked == False)  # noqa: E712
        .values(revoked=True)
    )
    await db.commit()
    return {"message": "All sessions have been revoked"}


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify the user's email via the token from the verification email."""
    from sqlalchemy import select
    from app.services.email_verification import mark_email_verified
    from datetime import timezone

    result = await db.execute(
        select(User).where(User.email_verification_token == body.token)
    )
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")

    if user.email_verified:
        # Idempotent: a user hitting refresh during set-password shouldn't 401.
        return {"message": "Email already verified", "email": user.email}

    if user.email_verification_token_expires_at and user.email_verification_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification link has expired. Please request a new one.")

    await mark_email_verified(db, user)
    await db.commit()

    return {"message": "Email verified successfully", "email": user.email}


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    body: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resend the account verification email. Rate-limited."""
    from app.services.email_verification import set_verification_token, send_verification_email
    from app.crud.user import get_user_by_email

    user = await get_user_by_email(db, body.email)
    # Always return success to avoid email enumeration
    if not user or user.email_verified:
        return {"message": "If that email exists and is unverified, a new link has been sent."}

    token = set_verification_token(user)
    db.add(user)
    await db.commit()

    await send_verification_email(user, token, temporary_password="[Use the password from your original email, or contact your admin]")

    return {"message": "If that email exists and is unverified, a new link has been sent."}


@router.post("/admin/revoke-user-tokens/{user_id}")
async def admin_revoke_user_tokens(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Admin: revoke all refresh tokens for a specific user (force logout)."""
    from app.core.deps import require_same_tenant
    from app.crud.user import get_user_by_id

    if current_user.role not in (UserRole.ADMIN, UserRole.PLATFORM_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can revoke other users' tokens",
        )

    target_user = await get_user_by_id(db, user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    require_same_tenant(target_user.tenant_id, current_user)

    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked == False)  # noqa: E712
        .values(revoked=True)
    )
    await db.commit()

    # Audit: admin forced logout
    await record_activity_events(db, [build_activity_event(
        activity_type="USER_TOKENS_REVOKED",
        visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
        tenant_id=current_user.tenant_id,
        actor_user=current_user,
        entity_type="user",
        entity_id=user_id,
        summary=f"{current_user.full_name} revoked all sessions for {target_user.full_name}.",
        route="/auth/admin/revoke-user-tokens",
        severity="warning",
    )])

    return {"message": f"All sessions revoked for user {target_user.full_name}"}


@router.post("/switch-role", response_model=TokenResponse)
@limiter.limit("30/minute")
async def switch_role(
    request: Request,
    body: RoleSwitchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Flip the current user's active role and return fresh tokens."""
    from app.db_tenant import tenant_session

    requested_role_value = body.role.value if hasattr(body.role, "value") else str(body.role)
    allowed = list(current_user.roles or [])

    if not allowed:
        # Pre-multi-role rows fall back to the active role.
        allowed = [
            current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        ]

    if requested_role_value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User is not authorized to act as {requested_role_value}.",
        )

    if requested_role_value == (
        current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already acting as that role.",
        )

    auth_hdr = request.headers.get("authorization", "")
    token_tenant_slug: str | None = None
    if auth_hdr.lower().startswith("bearer "):
        from app.core.security import decode_token
        payload = decode_token(auth_hdr[7:])
        if payload:
            token_tenant_slug = payload.get("tenant_slug")

    if token_tenant_slug:
        async with tenant_session(token_tenant_slug) as tenant_db:
            target = (await tenant_db.execute(
                select(User).where(User.id == current_user.id)
            )).scalar_one()
            target.role = body.role
            tenant_db.add(target)
            await tenant_db.commit()
            await record_activity_events(tenant_db, [build_activity_event(
                activity_type="ROLE_SWITCHED",
                visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                tenant_id=current_user.tenant_id,
                actor_user=target,
                entity_type="user",
                entity_id=target.id,
                summary=f"{target.full_name} switched active role to {requested_role_value}.",
                route="/auth/switch-role",
            )])
            target = await get_user_by_email(tenant_db, target.email)
    else:
        target = (await db.execute(
            select(User).where(User.id == current_user.id)
        )).scalar_one()
        target.role = body.role
        db.add(target)
        await db.commit()
        await record_activity_events(db, [build_activity_event(
            activity_type="ROLE_SWITCHED",
            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
            tenant_id=current_user.tenant_id,
            actor_user=target,
            entity_type="user",
            entity_id=target.id,
            summary=f"{target.full_name} switched active role to {requested_role_value}.",
            route="/auth/switch-role",
        )])
        target = await get_user_by_email(db, target.email)

    realm = "platform" if target.role == UserRole.PLATFORM_ADMIN else "tenant"
    payload = _build_token_payload(
        user_id=target.id,
        tenant_id=target.tenant_id,
        can_review=target.can_review,
        realm=realm,
        tenant_slug=token_tenant_slug,
    )
    access = create_access_token(payload)
    refresh, jti, expires_at = create_refresh_token(payload)

    if token_tenant_slug:
        async with tenant_session(token_tenant_slug) as tenant_db:
            tenant_db.add(RefreshToken(user_id=target.id, jti=jti, expires_at=expires_at))
            await tenant_db.commit()
    else:
        db.add(RefreshToken(user_id=target.id, jti=jti, expires_at=expires_at))
        await db.commit()

    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": target,
    }


@router.post("/role-handoff", response_model=RoleHandoffIssueResponse)
@limiter.limit("30/minute")
async def issue_role_handoff(
    request: Request,
    body: RoleSwitchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Mint a short-lived role-handoff token for opening another portal in a new tab."""
    from app.services.handoff import issue_role_handoff_token

    requested_role_value = body.role.value if hasattr(body.role, "value") else str(body.role)
    allowed = list(current_user.roles or [])
    if not allowed:
        allowed = [
            current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        ]
    if requested_role_value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User is not authorized to act as {requested_role_value}.",
        )

    auth_hdr = request.headers.get("authorization", "")
    token_tenant_slug: str | None = None
    if auth_hdr.lower().startswith("bearer "):
        from app.core.security import decode_token
        payload = decode_token(auth_hdr[7:])
        if payload:
            token_tenant_slug = payload.get("tenant_slug")

    handoff_token = await issue_role_handoff_token(
        user_id=current_user.id,
        target_role=requested_role_value,
        target_tenant_slug=token_tenant_slug,
    )

    await record_activity_events(db, [build_activity_event(
        activity_type="ROLE_HANDOFF_ISSUED",
        visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
        tenant_id=current_user.tenant_id,
        actor_user=current_user,
        entity_type="user",
        entity_id=current_user.id,
        summary=f"{current_user.full_name} initiated portal switch to {requested_role_value}.",
        route="/auth/role-handoff",
    )])

    return {
        "handoff_token": handoff_token,
        "target_role": body.role,
    }


@router.post("/role-handoff/exchange", response_model=TokenResponse)
@limiter.limit("30/minute")
async def exchange_role_handoff(
    request: Request,
    body: RoleHandoffExchangeRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Redeem a role-handoff token; returns a fresh access + refresh pair."""
    from app.services.handoff import redeem_role_handoff_token
    from app.db_tenant import tenant_session

    try:
        user_id, target_role_value, target_tenant_slug = await redeem_role_handoff_token(
            body.handoff_token
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )

    if target_tenant_slug:
        async with tenant_session(target_tenant_slug) as tenant_db:
            target = (await tenant_db.execute(
                select(User).where(User.id == user_id)
            )).scalar_one_or_none()
    else:
        target = (await db.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()

    if target is None or not target.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is not available.",
        )

    allowed = list(target.roles or [])
    if not allowed:
        allowed = [
            target.role.value if hasattr(target.role, "value") else str(target.role)
        ]
    if target_role_value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is no longer authorized for that role.",
        )

    try:
        new_role_enum = UserRole(target_role_value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unknown role {target_role_value!r}.",
        )

    realm = "platform" if new_role_enum == UserRole.PLATFORM_ADMIN else "tenant"
    # active_role on the token gives this tab its own session, independent
    # from the originating tab. Don't write users.role here — that column
    # is the user's last *explicit* choice (login or /auth/switch-role).
    payload = _build_token_payload(
        user_id=target.id,
        tenant_id=target.tenant_id,
        can_review=target.can_review,
        realm=realm,
        tenant_slug=target_tenant_slug,
        active_role=target_role_value,
    )
    access = create_access_token(payload)
    refresh, jti, expires_at = create_refresh_token(payload)

    if target_tenant_slug:
        async with tenant_session(target_tenant_slug) as tenant_db:
            tenant_db.add(RefreshToken(user_id=target.id, jti=jti, expires_at=expires_at))
            await tenant_db.commit()
            await record_activity_events(tenant_db, [build_activity_event(
                activity_type="ROLE_HANDOFF_REDEEMED",
                visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                tenant_id=target.tenant_id,
                actor_user=target,
                entity_type="user",
                entity_id=target.id,
                summary=f"{target.full_name} opened the {target_role_value} portal in a new tab.",
                route="/auth/role-handoff/exchange",
            )])
            target = await get_user_by_email(tenant_db, target.email)
    else:
        db.add(RefreshToken(user_id=target.id, jti=jti, expires_at=expires_at))
        await db.commit()
        await record_activity_events(db, [build_activity_event(
            activity_type="ROLE_HANDOFF_REDEEMED",
            visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
            tenant_id=target.tenant_id,
            actor_user=target,
            entity_type="user",
            entity_id=target.id,
            summary=f"{target.full_name} opened the {target_role_value} portal in a new tab.",
            route="/auth/role-handoff/exchange",
        )])
        target = await get_user_by_email(db, target.email)

    # Surface active role on response so the frontend renders the right portal.
    target.role = new_role_enum

    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": target,
    }
