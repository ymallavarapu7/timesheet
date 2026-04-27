from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from pydantic import BaseModel as PydanticBaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.schemas import ClientResponse, ClientCreate, ClientUpdate
from app.crud.client import get_client_by_id, create_client, update_client, delete_client, list_clients
from app.core.deps import get_current_user, require_role
from app.models.client import Client
from app.models.client_email_domain import ClientEmailDomain
from app.models.ingested_email import IngestedEmail
from app.models.ingestion_timesheet import IngestionTimesheet, IngestionTimesheetStatus
from app.models.user import User
from app.services.ingestion_pipeline import (
    PERSONAL_EMAIL_DOMAINS,
    _domain_of,
    is_personal_email_domain,
)
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


class CreateClientFromDomainRequest(PydanticBaseModel):
    """Body for POST /clients/from-domain.

    The reviewer typed a name in the inline-popover and confirmed; the
    backend creates the client, registers the domain mapping, and cascades
    the assignment to every pending ingestion timesheet from that domain
    in the tenant's queue.
    """
    name: str = Field(min_length=1, max_length=255, description="Client display name.")
    domain: str = Field(min_length=3, max_length=255, description="Email domain (e.g. 'dxc.com').")


class CreateClientFromDomainResponse(PydanticBaseModel):
    client: ClientResponse
    domain: str
    cascaded_count: int = Field(
        description="Number of pending ingestion timesheets that had their client_id set as a side-effect."
    )


def _email_domains_for_ingestion_timesheet(ts: IngestionTimesheet, email: IngestedEmail) -> set[str]:
    """All domains we'd consider for client resolution on a single timesheet.

    Mirrors the precedence used by the live resolver (forwarded-from →
    body emails → outer sender), but without the LLM-extracted name path
    since the cascade is strictly domain-based.
    """
    candidates: list[str] = []
    if email.forwarded_from_email:
        candidates.append(email.forwarded_from_email)
    if email.sender_email:
        candidates.append(email.sender_email)
    extracted = ts.extracted_data or {}
    body_emails = extracted.get("contact_emails") or []
    if isinstance(body_emails, list):
        candidates.extend(str(e) for e in body_emails if e)
    chain = email.chain_senders or []
    if isinstance(chain, list):
        for entry in chain:
            if isinstance(entry, dict) and entry.get("email"):
                candidates.append(str(entry["email"]))
    return {_domain_of(c) for c in candidates if c} - {""}


@router.post(
    "/from-domain",
    response_model=CreateClientFromDomainResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_client_from_domain(
    body: CreateClientFromDomainRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> dict:
    """
    Create a client whose email domain is registered, then cascade the
    assignment to every pending ingestion timesheet in the tenant's queue
    whose sender/forwarded/body email domain matches.

    Refuses personal email domains (gmail, outlook, etc.) — those are never
    legitimate client identities. Returns 409 with the existing client info
    if the domain is already mapped, so the frontend can offer a 'link to
    that client' alternative.
    """
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PLATFORM_ADMIN must operate within a tenant context for this action.",
        )
    tenant_id = current_user.tenant_id

    name = body.name.strip()
    domain = body.domain.strip().lower()
    if "@" in domain:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="domain must be the bare domain (e.g. 'dxc.com'), not an email address.",
        )
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="name is required.",
        )
    if is_personal_email_domain(domain):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"'{domain}' is a personal email provider and cannot be mapped to a client. "
                "Pick an existing client manually for emails from this domain."
            ),
        )

    # Reject if domain is already mapped in this tenant — return existing
    # client info so the UI can offer 'link to it instead'.
    existing_q = await db.execute(
        select(ClientEmailDomain.client_id, Client.name)
        .join(Client, Client.id == ClientEmailDomain.client_id)
        .where(
            (ClientEmailDomain.tenant_id == tenant_id)
            & (ClientEmailDomain.domain == domain)
        )
    )
    existing_row = existing_q.first()
    if existing_row is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "domain_already_mapped",
                "message": f"Domain '{domain}' is already mapped to client '{existing_row.name}'.",
                "existing_client_id": existing_row.client_id,
                "existing_client_name": existing_row.name,
            },
        )

    # Create the Client + domain mapping in one transaction. Inlined
    # rather than calling crud.create_client because that helper commits
    # eagerly, which would leave a Client row orphaned if the cascade
    # below failed.
    new_client = Client(name=name, tenant_id=tenant_id)
    db.add(new_client)
    try:
        await db.flush()  # populates new_client.id without committing
    except Exception as exc:
        await db.rollback()
        # Most likely a duplicate name — the unique constraint
        # (tenant_id, name) on Client surfaces here.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A client named '{name}' already exists in this tenant.",
        ) from exc

    # Register the domain mapping.
    db.add(ClientEmailDomain(
        tenant_id=tenant_id,
        client_id=new_client.id,
        domain=domain,
    ))

    # Cascade: find pending ingestion timesheets in this tenant with
    # client_id IS NULL whose linked email's domain matches, and assign
    # the new client. Done in Python because the candidate domain may
    # come from JSON fields (extracted_data.contact_emails, chain_senders).
    pending_q = await db.execute(
        select(IngestionTimesheet, IngestedEmail)
        .join(IngestedEmail, IngestedEmail.id == IngestionTimesheet.email_id)
        .where(
            (IngestionTimesheet.tenant_id == tenant_id)
            & (IngestionTimesheet.client_id.is_(None))
            & (IngestionTimesheet.status == IngestionTimesheetStatus.pending)
        )
    )
    matched_ids: list[int] = []
    for ts, email in pending_q.all():
        if domain in _email_domains_for_ingestion_timesheet(ts, email):
            matched_ids.append(ts.id)

    if matched_ids:
        await db.execute(
            update(IngestionTimesheet)
            .where(IngestionTimesheet.id.in_(matched_ids))
            .values(client_id=new_client.id)
        )

    await record_activity_events(
        db,
        [
            build_activity_event(
                activity_type="CLIENT_CREATED",
                visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                tenant_id=tenant_id,
                actor_user=current_user,
                entity_type="client",
                entity_id=new_client.id,
                summary=(
                    f"{current_user.full_name} created client {new_client.name} "
                    f"from domain {domain} (cascaded to {len(matched_ids)} pending email"
                    f"{'' if len(matched_ids) == 1 else 's'})."
                ),
                route="/client-management",
                route_params={"clientId": new_client.id},
                metadata={
                    "client_name": new_client.name,
                    "domain": domain,
                    "cascaded_count": len(matched_ids),
                },
            )
        ],
    )
    await db.commit()
    await db.refresh(new_client)

    return {
        "client": new_client,
        "domain": domain,
        "cascaded_count": len(matched_ids),
    }


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
