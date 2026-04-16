from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.schemas import ClientResponse, ClientCreate, ClientUpdate
from app.crud.client import get_client_by_id, create_client, update_client, delete_client, list_clients
from app.core.deps import get_current_user, require_role
from app.models.user import User
from app.services.ingestion_sync import _send_outbound_webhook
from app.services.activity import (
    TENANT_ADMIN_ACTIVITY_SCOPE,
    build_activity_event,
    record_activity_events,
)

router = APIRouter(prefix="/clients", tags=["clients"])


async def _try_outbound_webhook(**kwargs) -> None:
    """Fire-and-forget wrapper — swallows all exceptions so a webhook failure never breaks the response."""
    try:
        await _send_outbound_webhook(**kwargs)
    except Exception:
        pass


@router.get("", response_model=list[ClientResponse])
async def list_all_clients(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list:
    """
    List all clients within the current user's tenant.
    Any authenticated user can view clients.
    """
    return await list_clients(db, tenant_id=current_user.tenant_id, skip=skip, limit=limit)


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Get a specific client by ID.
    """
    client = await get_client_by_id(db, client_id, tenant_id=current_user.tenant_id)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return client


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_new_client(
    client_create: ClientCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> dict:
    """
    Create a new client (Admin only).
    """
    new_client = await create_client(db, client_create, tenant_id=current_user.tenant_id)
    if new_client.tenant_id is not None:
        await record_activity_events(
            db,
            [
                build_activity_event(
                    activity_type="CLIENT_CREATED",
                    visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                    tenant_id=new_client.tenant_id,
                    actor_user=current_user,
                    entity_type="client",
                    entity_id=new_client.id,
                    summary=f"{current_user.full_name} created client {new_client.name}.",
                    route="/client-management",
                    route_params={"clientId": new_client.id},
                    metadata={"client_name": new_client.name},
                )
            ],
        )
    return new_client


@router.put("/{client_id}", response_model=ClientResponse)
async def update_client_endpoint(
    client_id: int,
    client_update: ClientUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> dict:
    """
    Update a client (Admin only).
    """
    client = await get_client_by_id(db, client_id, tenant_id=current_user.tenant_id)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    # Build changed_fields before updating (for outbound webhook)
    changed_fields = {}
    update_data = client_update.model_dump(exclude_unset=True)
    for field, new_val in update_data.items():
        old_val = getattr(client, field, None)
        if old_val != new_val:
            changed_fields[field] = {"old": old_val, "new": new_val}

    updated_client = await update_client(db, client, client_update)

    if client.ingestion_client_id and changed_fields:
        background_tasks.add_task(
            _try_outbound_webhook,
            tenant_id=current_user.tenant_id,
            event_type="client.updated",
            local_id=client.id,
            ingestion_id=client.ingestion_client_id,
            changed_fields=changed_fields,
            changed_by_name=current_user.full_name,
            session=db,
        )

    return updated_client


class BulkDeleteClientsRequest(PydanticBaseModel):
    client_ids: list[int]


@router.post("/bulk-delete")
async def bulk_delete_clients(
    body: BulkDeleteClientsRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> dict:
    deleted = 0
    for client_id in body.client_ids:
        client = await get_client_by_id(db, client_id, tenant_id=current_user.tenant_id)
        if not client:
            continue
        ingestion_client_id = client.ingestion_client_id
        client_id_local = client.id
        success = await delete_client(db, client_id, tenant_id=current_user.tenant_id)
        if not success:
            continue
        deleted += 1
        if ingestion_client_id:
            background_tasks.add_task(
                _try_outbound_webhook,
                tenant_id=current_user.tenant_id,
                event_type="client.deleted",
                local_id=client_id_local,
                ingestion_id=ingestion_client_id,
                changed_fields={},
                changed_by_name=current_user.full_name,
                session=db,
            )
    return {"deleted": deleted}


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client_endpoint(
    client_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> None:
    """
    Delete a client (Admin only).
    """
    client = await get_client_by_id(db, client_id, tenant_id=current_user.tenant_id)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    ingestion_client_id = client.ingestion_client_id
    client_id_local = client.id

    success = await delete_client(db, client_id, tenant_id=current_user.tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    if ingestion_client_id:
        background_tasks.add_task(
            _try_outbound_webhook,
            tenant_id=current_user.tenant_id,
            event_type="client.deleted",
            local_id=client_id_local,
            ingestion_id=ingestion_client_id,
            changed_fields={},
            changed_by_name=current_user.full_name,
            session=db,
        )
