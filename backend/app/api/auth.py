from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.schemas import LoginRequest, TokenResponse, UserResponse, UserCreate, ChangePasswordRequest, PasswordChangeResponse, RefreshRequest, VerifyEmailRequest, VerifyEmailResponse, ResendVerificationRequest, MessageResponse
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
    if current_user.role.value not in ("ADMIN", "PLATFORM_ADMIN"):
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
    """
    Login with email and password, return JWT tokens.
    Account is locked for 15 minutes after 5 consecutive failed attempts.
    """
    # Find user
    user = await get_user_by_email(db, login_request.email)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

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

    # Successful login — reset lockout counters
    user.failed_login_attempts = 0
    user.locked_until = None
    db.add(user)
    await db.commit()

    # Create tokens — include tenant_id so the server can verify it on each request.
    # tenant_id is None for PLATFORM_ADMIN users.
    token_payload = {
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
        "can_review": user.can_review,
    }
    access_token = create_access_token(token_payload)
    refresh_token, jti, expires_at = create_refresh_token(token_payload)

    # Persist refresh token for revocation support
    db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=expires_at))
    await db.commit()

    # Audit: successful login
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

    # Re-fetch user with eager-loaded relationships so response serialisation
    # doesn't hit expired attributes after the commits above.
    user = await get_user_by_email(db, user.email)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user,
    }


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
async def refresh_token(
    request: Request,
    body: RefreshRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Refresh access token using a refresh token from request body."""
    from app.core.security import decode_token
    token = body.refresh_token if body else None
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token provided")

    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user_id = payload.get("sub")
    jti = payload.get("jti")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    # Validate refresh token against DB (revocation check)
    if jti:
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.jti == jti)
        )
        stored_token = result.scalars().first()
        if not stored_token or stored_token.revoked:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has been revoked")
        # Revoke the old refresh token (single-use rotation)
        stored_token.revoked = True
        db.add(stored_token)

    from app.crud.user import get_user_by_id
    user = await get_user_by_id(db, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    token_payload = {
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
        "can_review": user.can_review,
    }
    access_token = create_access_token(token_payload)
    new_refresh_token, new_jti, new_expires_at = create_refresh_token(token_payload)

    # Persist the new refresh token
    db.add(RefreshToken(user_id=user.id, jti=new_jti, expires_at=new_expires_at))
    await db.commit()

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
    """
    Get current authenticated user info.
    """
    return current_user


@router.post("/change-password", response_model=PasswordChangeResponse)
async def change_password(
    change_password_request: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Change the current user's password.
    """
    # Verify current password
    if not verify_password(change_password_request.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    # Enforce password policy
    from app.core.password_policy import validate_password
    error = validate_password(change_password_request.new_password)
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    # Update password
    current_user.hashed_password = get_password_hash(
        change_password_request.new_password)
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
    """
    Verify a user's email address using the token from the verification email.
    Also marks has_changed_password=True (password was set during verification).
    """
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
        return {"message": "Email already verified"}

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
    """
    Resend the account verification email. Admin-initiated action or self-service.
    Rate-limited to prevent abuse.
    """
    from app.services.email_verification import set_verification_token, send_verification_email
    from app.crud.user import get_user_by_email

    user = await get_user_by_email(db, body.email)
    # Always return success to avoid email enumeration
    if not user or user.email_verified:
        return {"message": "If that email exists and is unverified, a new link has been sent."}

    # Generate a new token and a placeholder temp-password note
    # (the original temp password is unknown after creation; user must use forgot-password if they lost it)
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

    if current_user.role.value not in ("ADMIN", "PLATFORM_ADMIN"):
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
