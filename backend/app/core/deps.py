from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import decode_token, split_service_token, verify_service_token
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

    Resolution order:
      1. ``X-Tenant-Slug`` header. Only honored for ``realm=platform``
         tokens (platform admins acting as a tenant). Tenant-realm
         tokens ignore the header to prevent tenant escape.
      2. ``tenant_slug`` claim on the JWT.
      3. Legacy fallback when no slug is resolvable (tokens minted
         before 3.B): use the shared ``app.db.get_db`` session. Phase
         3.C+ removes this path once every issued token has a slug.

    Resolver behavior (Phase 3.C): ``app.db_tenant`` reads the
    control-plane ``tenants`` row. When ``is_isolated=True`` and a
    ``db_name`` is set, the session binds to the per-tenant database;
    otherwise it binds to the shared ``timesheet_db``. While
    ``is_isolated`` stays False on every tenant, swapping
    ``Depends(get_db)`` to ``Depends(get_tenant_db)`` is a behavioral
    no-op.

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

    try:
        factory = await get_session_factory_for_slug(slug)
    except LookupError as exc:
        # Slug came from the JWT or from a header. Either way the
        # caller handed us an identifier that doesn't exist in the
        # control plane -- treat it as unauthenticated, never 500.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown tenant",
        ) from exc
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

        # Phase 3.C: when the token carries a tenant_slug, the per-tenant
        # database is the source of truth for the user row. Reload from
        # the tenant DB so columns written there (profile edits, roles
        # array changes, etc.) are visible. Without this refresh,
        # get_current_user would serve stale values from the legacy
        # shared DB. Tokens minted before 3.B (no tenant_slug) keep the
        # legacy single-DB path.
        token_tenant_slug = payload.get("tenant_slug")
        if token_tenant_slug:
            from app.db_tenant import tenant_session
            try:
                async with tenant_session(token_tenant_slug) as tenant_db:
                    refreshed = await get_user_by_id(tenant_db, user_id)
                if refreshed is not None:
                    user = refreshed
            except (LookupError, ValueError) as exc:
                logger.warning(
                    "tenant DB refresh failed for slug=%s user=%s: %s",
                    token_tenant_slug, user_id, exc,
                )

        # Multi-role support: when the token carries an active_role
        # claim, that's the role this request is acting as (independent
        # of users.role on disk). The claim must still be inside the
        # user's allowed roles list — a token cannot grant a role the
        # user isn't authorized for. Tokens minted before this feature
        # have no claim and fall through to the DB column.
        token_active_role = payload.get("active_role")
        if token_active_role:
            allowed_roles = list(user.roles or [])
            if not allowed_roles:
                allowed_roles = [
                    user.role.value if hasattr(user.role, "value") else str(user.role)
                ]
            if token_active_role not in allowed_roles:
                logger.warning(
                    "Token active_role=%s not in user.roles=%s for user_id=%s",
                    token_active_role, allowed_roles, user_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token role is no longer authorized.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            try:
                user.role = UserRole(token_active_role)
            except ValueError:
                logger.warning("Token active_role=%r not a valid UserRole", token_active_role)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token role is invalid.",
                    headers={"WWW-Authenticate": "Bearer"},
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

    # Token format: ``<token_id>.<secret>`` for new-format tokens. We
    # look up by the indexed token_id (one row), then bcrypt-verify
    # only the secret. Legacy tokens (no dot) fall through to the
    # historical loop-and-compare path so existing deployments keep
    # working until they rotate.
    token_id, secret = split_service_token(raw_token)
    matched_token: ServiceToken | None = None

    if token_id is not None:
        stored = (await db.execute(
            select(ServiceToken).where(
                (ServiceToken.token_id == token_id) &
                (ServiceToken.tenant_id == tenant_id) &
                (ServiceToken.is_active == True)  # noqa: E712
            )
        )).scalar_one_or_none()
        if stored is not None and verify_service_token(secret, stored.token_hash):
            matched_token = stored
    else:
        # Legacy fallback: pre-041 tokens have no token_id. Sweep the
        # active tokens for this tenant. Slow with many tokens, but
        # only fires for un-rotated legacy tokens.
        result = await db.execute(
            select(ServiceToken).where(
                (ServiceToken.tenant_id == tenant_id) &
                (ServiceToken.is_active == True) &  # noqa: E712
                (ServiceToken.token_id.is_(None))
            )
        )
        for stored in result.scalars().all():
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


def get_tenant_slug(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Return the caller's tenant slug.

    Mirrors ``get_tenant_db``'s slug-resolution rules so workers
    enqueued from a route can pass the slug into the job payload
    without paying a control-plane lookup later. Tenant-realm tokens
    use the ``tenant_slug`` JWT claim; platform-realm tokens require
    the ``X-Tenant-Slug`` header (so a platform admin acting on a
    tenant must declare which one).

    Raises 400 for platform-realm without header, 401 for invalid
    token, 403 for tenant-realm tokens missing the slug claim
    (which would only happen on tokens minted before 3.B).
    """
    payload = _decode_or_raise(credentials)
    realm = payload.get("realm", "tenant")
    if realm == "platform":
        slug = request.headers.get("X-Tenant-Slug")
        if not slug:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Platform-admin tokens must specify a tenant via the "
                    "X-Tenant-Slug header to access tenant-scoped routes."
                ),
            )
        return slug
    slug = payload.get("tenant_slug")
    if not slug:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token has no tenant_slug claim; re-authenticate.",
        )
    return slug


async def require_ingestion_enabled(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
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

    Admin is intentionally excluded: a user who is both an admin and a
    reviewer logs in with their manager account for review work. The
    admin portal carries admin duties only.
    """
    if current_user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role does not have reviewer access. Log in with your manager account.",
        )
    if not current_user.can_review:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have reviewer access.",
        )
    return current_user
