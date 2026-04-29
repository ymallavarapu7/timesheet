from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import decode_token, verify_service_token
from app.db import get_db
from app.db_tenant import get_session_factory_for_slug
from app.models import User
from app.models.user import UserRole
from app.models.service_token import ServiceToken
import logging

logger = logging.getLogger(__name__)
security = HTTPBearer()


def _decode_or_raise(credentials: HTTPAuthorizationCredentials) -> dict:
    """Decode the JWT or raise 401. Shared by every dep that needs the
    payload before the user object is loaded."""
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def get_tenant_db(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """FastAPI dependency: yield a session bound to the caller's
    tenant database.

    Phase 3.B note: this dep is wired and available, but no endpoint
    uses it yet. Every tenant still points at the shared ``timesheet_db``
    so swapping ``Depends(get_db)`` to ``Depends(get_tenant_db)`` is a
    behavioral no-op today. The bulk endpoint refactor lands in 3.C
    alongside the actual per-tenant database split, which is when the
    resolver materially changes behavior.

    Resolution order (when callers do start using it):
      1. ``X-Tenant-Slug`` header. Only honored for ``realm=platform``
         tokens (platform admins acting as a tenant). Tenant-realm
         tokens ignore the header to prevent tenant escape.
      2. ``tenant_slug`` claim on the JWT.
      3. Legacy fallback when no slug is resolvable (tokens minted
         before 3.B): use the shared ``app.db.get_db`` session. Phase
         3.C removes this path once every issued token has a slug.

    Routes that operate on cross-tenant data (tenants directory,
    platform settings, system health) should depend on
    ``app.db_control.get_control_db`` instead.
    """
    payload = _decode_or_raise(credentials)
    realm = payload.get("realm", "tenant")
    slug: str | None = None

    if realm == "platform":
        header_slug = request.headers.get("X-Tenant-Slug")
        if not header_slug:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Platform-admin tokens must specify a tenant via the "
                    "X-Tenant-Slug header to access tenant-scoped routes."
                ),
            )
        slug = header_slug
    else:
        slug = payload.get("tenant_slug")

    if not slug:
        async for session in get_db():
            yield session
        return

    factory = await get_session_factory_for_slug(slug)
    async with factory() as session:
        yield session


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Extract and validate current user from JWT token.
    Also verifies that the tenant_id in the token matches the database record.
    Raises HTTPException if token is invalid or user not found.
    """
    from app.crud.user import get_user_by_id

    try:
        token = credentials.credentials
        logger.debug("Validating token")

        payload = decode_token(token)
        if payload is None:
            logger.warning("Token decode failed")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        sub = payload.get("sub")
        if not sub:
            logger.warning("No user_id in payload")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            user_id = int(sub)
        except (ValueError, TypeError):
            logger.warning("Invalid user_id in payload")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user_id:
            logger.warning("No user_id in payload")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Extract tenant_id from token — may be None for PLATFORM_ADMIN
        token_tenant_id = payload.get("tenant_id")
        token_realm = payload.get("realm", "tenant")

        # Phase 3.B: realm-aware lookup. Platform-admin tokens load
        # against the control plane and return a synthetic ``User``-
        # shaped record so existing routes that read scalar columns
        # off ``current_user`` continue to work unchanged. The adapter
        # is intentionally not bound to either session — every code
        # path we audited reads columns only, never relationships, so
        # a detached object is sufficient.
        if token_realm == "platform":
            from app.db_control import AsyncControlSessionLocal
            from app.models.control import PlatformAdmin
            async with AsyncControlSessionLocal() as control_db:
                pa = await control_db.get(PlatformAdmin, user_id)
            if pa is None:
                logger.warning(f"PlatformAdmin {user_id} not found")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if not pa.is_active:
                logger.warning(f"PlatformAdmin {user_id} is inactive")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Inactive user",
                )
            adapter = User()
            adapter.id = pa.id
            adapter.tenant_id = None
            adapter.email = pa.email
            adapter.username = pa.username
            adapter.full_name = pa.full_name
            adapter.title = None
            adapter.department = None
            adapter.timezone = "UTC"
            adapter.role = UserRole.PLATFORM_ADMIN
            adapter.is_active = pa.is_active
            adapter.has_changed_password = pa.has_changed_password
            adapter.email_verified = pa.email_verified
            adapter.can_review = False
            adapter.is_external = False
            adapter.timesheet_locked = False
            adapter.failed_login_attempts = 0
            adapter.locked_until = None
            adapter.created_at = pa.created_at
            adapter.updated_at = pa.updated_at
            request.state.current_user = adapter
            return adapter

        user = await get_user_by_id(db, user_id)
        if user is None:
            logger.warning(f"User {user_id} not found")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            logger.warning(f"User {user_id} is inactive")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inactive user",
            )

        # Verify the tenant_id encoded in the token matches what is in the DB.
        # This prevents a token issued before a user was moved between tenants
        # from being used with the wrong tenant context.
        if user.tenant_id != token_tenant_id:
            logger.warning(
                f"User {user_id} tenant mismatch: token={token_tenant_id}, db={user.tenant_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.debug("User validated successfully")
        request.state.current_user = user
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_current_user: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        )


def require_role(*allowed_roles: str):
    """
    Dependency to check if user has one of the allowed roles.
    Usage: Depends(require_role("ADMIN"))
    """
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.value not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User role {current_user.role} is not authorized",
            )
        return current_user

    return role_checker


def require_same_tenant(resource_tenant_id: int, current_user: User) -> None:
    """
    Raise 403 if the resource does not belong to the current user's tenant.
    PLATFORM_ADMIN bypasses this check and can access any tenant's resources.
    Call this inside route handlers after fetching a resource by ID.
    """
    if current_user.role == UserRole.PLATFORM_ADMIN:
        return
    if resource_tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: resource belongs to a different tenant",
        )


SERVICE_TOKEN_HEADER = "X-Service-Token"
SERVICE_TENANT_HEADER = "X-Tenant-ID"


async def get_service_token_tenant(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple[int, ServiceToken]:
    """
    Dependency for sync endpoints.
    Reads X-Service-Token and X-Tenant-ID headers.
    Validates the token against stored hashes for the given tenant.
    Returns (tenant_id, service_token_record).

    Raises 401 if token is missing, invalid, or inactive.
    """
    raw_token = request.headers.get(SERVICE_TOKEN_HEADER)
    tenant_id_header = request.headers.get(SERVICE_TENANT_HEADER)

    if not raw_token or not tenant_id_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing service token or tenant ID header",
        )

    try:
        tenant_id = int(tenant_id_header)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID must be an integer",
        )

    # Load all active tokens for this tenant and verify against each
    result = await db.execute(
        select(ServiceToken).where(
            (ServiceToken.tenant_id == tenant_id) &
            (ServiceToken.is_active == True)  # noqa: E712
        )
    )
    tokens = result.scalars().all()

    matched_token = None
    for stored in tokens:
        if verify_service_token(raw_token, stored.token_hash):
            matched_token = stored
            break

    if not matched_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive service token",
        )

    # Update last_used_at (non-blocking — don't fail the request if this fails)
    try:
        from datetime import datetime, timezone
        matched_token.last_used_at = datetime.now(timezone.utc).isoformat()
        await db.commit()
    except Exception as e:
        logger.warning("Failed to update service token last_used_at: %s", e)

    return tenant_id, matched_token


def get_tenant_id(current_user: User = Depends(get_current_user)) -> int:
    """
    Return the current user's tenant_id.
    Use as a dependency in route handlers that need the tenant scope without
    repeating the check inline.
    Raises 403 if a non-PLATFORM_ADMIN user somehow has no tenant assignment.
    """
    if current_user.tenant_id is None and current_user.role != UserRole.PLATFORM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no tenant assignment",
        )
    return current_user.tenant_id


async def require_ingestion_enabled(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Verify the current user's tenant has ingestion enabled.
    """
    from app.models.tenant import Tenant

    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email ingestion is not available without a tenant assignment.",
        )

    tenant = await db.get(Tenant, current_user.tenant_id)
    if not tenant or not tenant.ingestion_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Email ingestion is not enabled for this tenant. "
                "Contact your platform administrator."
            ),
        )
    return current_user


async def require_can_review(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Verify the current user can access the reviewer inbox.
    """
    if current_user.role == UserRole.ADMIN:
        return current_user
    if not current_user.can_review:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have reviewer access.",
        )
    return current_user
