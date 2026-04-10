from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from app.models.client import Client
from app.schemas import ClientCreate, ClientUpdate
from typing import Optional


async def get_client_by_id(db: AsyncSession, client_id: int, tenant_id: Optional[int] = None) -> Optional[Client]:
    """Get client by ID, scoped to a tenant. Pass tenant_id=None only for PLATFORM_ADMIN."""
    query = select(Client).where(Client.id == client_id)
    if tenant_id is not None:
        query = query.where(Client.tenant_id == tenant_id)
    result = await db.execute(query)
    return result.scalars().first()


async def get_client_by_name(db: AsyncSession, name: str, tenant_id: int) -> Optional[Client]:
    """Get client by name scoped to a tenant."""
    result = await db.execute(
        select(Client).where(Client.name == name, Client.tenant_id == tenant_id)
    )
    return result.scalars().first()


async def create_client(db: AsyncSession, client_create: ClientCreate, tenant_id: int) -> Client:
    """Create a new client."""
    db_client = Client(**client_create.model_dump(), tenant_id=tenant_id)
    db.add(db_client)
    try:
        await db.commit()
        await db.refresh(db_client)
    except IntegrityError:
        await db.rollback()
        raise
    return db_client


async def update_client(db: AsyncSession, client: Client, client_update: ClientUpdate) -> Client:
    """Update client fields."""
    update_data = client_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(client, field, value)

    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


async def delete_client(db: AsyncSession, client_id: int, tenant_id: Optional[int] = None) -> bool:
    """Delete client by ID, scoped to a tenant."""
    client = await get_client_by_id(db, client_id, tenant_id=tenant_id)
    if client:
        await db.delete(client)
        await db.commit()
        return True
    return False


async def list_clients(db: AsyncSession, tenant_id: int, skip: int = 0, limit: int = 100) -> list[Client]:
    """List clients for a tenant with pagination."""
    result = await db.execute(
        select(Client)
        .where(Client.tenant_id == tenant_id)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()
