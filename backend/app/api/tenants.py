import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_role
from app.core.security import generate_service_token, get_password_hash, hash_service_token
from app.crud.tenant import create_tenant, get_tenant, get_tenant_by_slug, list_tenants, update_tenant
from app.models.service_token import ServiceToken
from app.schemas import TenantCreate, TenantResponse, TenantUpdate
from app.schemas.sync import ServiceTokenCreate, ServiceTokenRead, ServiceTokenCreatedResponse
from app.models.user import User, UserRole
from app.services.activity import (
    PLATFORM_ADMIN_ACTIVITY_SCOPE,
    build_activity_event,
    record_activity_events,
)

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("/mine", response_model=TenantResponse)
async def get_my_tenant(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> object:
    """Get the current user's own tenant. Any authenticated user can call this."""
    if not current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tenant assigned")
    tenant = await get_tenant(db, current_user.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


@router.get("", response_model=list[TenantResponse])
async def list_all_tenants(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_role("PLATFORM_ADMIN")),
) -> list:
    """List all tenants (PLATFORM_ADMIN only)."""
    return await list_tenants(db)


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_new_tenant(
    tenant_in: TenantCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("PLATFORM_ADMIN")),
) -> object:
    """Create a new tenant (PLATFORM_ADMIN only)."""
    existing = await get_tenant_by_slug(db, tenant_in.slug)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slug already in use",
        )
    tenant = await create_tenant(db, tenant_in.name, tenant_in.slug)
    await record_activity_events(
        db,
        [
            build_activity_event(
                activity_type="TENANT_CREATED",
                visibility_scope=PLATFORM_ADMIN_ACTIVITY_SCOPE,
                tenant_id=tenant.id,
                actor_user=current_user,
                entity_type="tenant",
                entity_id=tenant.id,
                summary=f"{current_user.full_name} created tenant {tenant.name}.",
                route="/platform-admin",
                route_params={"tenantId": tenant.id},
                metadata={"tenant_name": tenant.name, "status": tenant.status.value},
            )
        ],
    )
    return tenant


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant_endpoint(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_role("PLATFORM_ADMIN")),
) -> object:
    """Get a specific tenant (PLATFORM_ADMIN only)."""
    tenant = await get_tenant(db, tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    return tenant


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant_endpoint(
    tenant_id: int,
    tenant_in: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("PLATFORM_ADMIN")),
) -> object:
    """Update a tenant (PLATFORM_ADMIN only)."""
    tenant = await get_tenant(db, tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    previous_name = tenant.name
    previous_slug = tenant.slug
    previous_status = tenant.status
    updated_tenant = await update_tenant(db, tenant, **tenant_in.model_dump(exclude_unset=True))

    activity_events: list[dict] = []
    if previous_status != updated_tenant.status:
        activity_events.append(
            build_activity_event(
                activity_type="TENANT_STATUS_CHANGED",
                visibility_scope=PLATFORM_ADMIN_ACTIVITY_SCOPE,
                tenant_id=updated_tenant.id,
                actor_user=current_user,
                entity_type="tenant",
                entity_id=updated_tenant.id,
                summary=f"{current_user.full_name} changed {updated_tenant.name} from {previous_status.value} to {updated_tenant.status.value}.",
                route="/platform-admin",
                route_params={"tenantId": updated_tenant.id},
                metadata={"old_status": previous_status.value, "new_status": updated_tenant.status.value},
            )
        )

    if previous_name != updated_tenant.name or previous_slug != updated_tenant.slug:
        activity_events.append(
            build_activity_event(
                activity_type="TENANT_UPDATED",
                visibility_scope=PLATFORM_ADMIN_ACTIVITY_SCOPE,
                tenant_id=updated_tenant.id,
                actor_user=current_user,
                entity_type="tenant",
                entity_id=updated_tenant.id,
                summary=f"{current_user.full_name} updated tenant {previous_name}.",
                route="/platform-admin",
                route_params={"tenantId": updated_tenant.id},
                metadata={
                    "old_name": previous_name,
                    "new_name": updated_tenant.name,
                    "old_slug": previous_slug,
                    "new_slug": updated_tenant.slug,
                },
            )
        )

    await record_activity_events(db, activity_events)
    return updated_tenant


@router.post("/{tenant_id}/service-tokens",
             response_model=ServiceTokenCreatedResponse,
             status_code=status.HTTP_201_CREATED)
async def create_service_token(
    tenant_id: int,
    token_in: ServiceTokenCreate,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_role("PLATFORM_ADMIN")),
) -> object:
    """
    Creates a new service token for a tenant.
    Returns the plaintext token ONCE — it cannot be retrieved again.
    The ingestion platform must store this token securely.
    """
    tenant = await get_tenant(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # New-format tokens (post-041) embed a public token_id prefix so
    # the auth dep does an indexed lookup instead of a per-tenant
    # bcrypt sweep. We only persist the secret half — the prefix is
    # stored verbatim alongside it.
    plaintext, token_id, secret = generate_service_token()
    token_record = ServiceToken(
        name=token_in.name,
        token_id=token_id,
        token_hash=hash_service_token(secret),
        tenant_id=tenant_id,
        issuer=token_in.issuer,
        is_active=True,
    )
    db.add(token_record)
    await db.commit()
    await db.refresh(token_record)

    return ServiceTokenCreatedResponse(
        id=token_record.id,
        name=token_record.name,
        tenant_id=token_record.tenant_id,
        issuer=token_record.issuer,
        is_active=token_record.is_active,
        last_used_at=token_record.last_used_at,
        created_at=token_record.created_at,
        token=plaintext,
    )


@router.get("/{tenant_id}/service-tokens",
            response_model=list[ServiceTokenRead])
async def list_service_tokens(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_role("PLATFORM_ADMIN")),
) -> list:
    """List service tokens for a tenant. Token values are never returned."""
    result = await db.execute(
        select(ServiceToken).where(ServiceToken.tenant_id == tenant_id)
    )
    return result.scalars().all()


@router.delete("/{tenant_id}/service-tokens/{token_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def revoke_service_token(
    tenant_id: int,
    token_id: int,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_role("PLATFORM_ADMIN")),
) -> None:
    """Deactivate a service token. The ingestion platform will get 401s."""
    token = await db.get(ServiceToken, token_id)
    if not token or token.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Token not found")
    token.is_active = False
    await db.commit()


@router.post("/{tenant_id}/provision-system-user", status_code=status.HTTP_200_OK)
async def provision_system_user(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_role("PLATFORM_ADMIN")),
) -> dict:
    """
    Ensure the ingestion system service user exists for the given tenant.
    Safe to call multiple times — idempotent.
    """
    tenant = await get_tenant(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    username = f"system_ingestion_{tenant_id}"
    email = f"system_ingestion_{tenant_id}@system.internal"

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user:
        return {"provisioned": False, "user_id": user.id, "email": email}

    user = User(
        tenant_id=tenant_id,
        email=email,
        username=username,
        full_name="Ingestion System",
        hashed_password=get_password_hash(secrets.token_urlsafe(48)),
        role=UserRole.EMPLOYEE,
        is_active=True,
        has_changed_password=True,
        can_review=False,
        is_external=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return {"provisioned": True, "user_id": user.id, "email": email}
