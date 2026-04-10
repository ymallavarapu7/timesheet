from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.tenant import Tenant, TenantStatus


async def get_tenant(db: AsyncSession, tenant_id: int) -> Tenant | None:
    return await db.get(Tenant, tenant_id)


async def get_tenant_by_slug(db: AsyncSession, slug: str) -> Tenant | None:
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    return result.scalar_one_or_none()


async def list_tenants(db: AsyncSession) -> list[Tenant]:
    result = await db.execute(select(Tenant).order_by(Tenant.name))
    return list(result.scalars().all())


async def create_tenant(db: AsyncSession, name: str, slug: str) -> Tenant:
    tenant = Tenant(name=name, slug=slug, status=TenantStatus.active)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def update_tenant(db: AsyncSession, tenant: Tenant, **kwargs) -> Tenant:
    for key, value in kwargs.items():
        setattr(tenant, key, value)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant
