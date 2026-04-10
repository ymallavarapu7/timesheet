"""
Sync endpoints — called by the ingestion platform only.
All endpoints require service token authentication via X-Service-Token header.
Tenant ID is read from X-Tenant-ID header, not the URL or body.
"""

import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.deps import get_db, get_service_token_tenant
from app.models.client import Client
from app.models.sync_log import SyncLog, SyncDirection, SyncEntityType, SyncStatus
from app.schemas.sync import (
    SyncEmployeeRequest, SyncEmployeeResponse,
    SyncClientRequest, SyncClientResponse,
    SyncProjectRequest, SyncProjectResponse,
    PushTimesheetRequest, PushTimesheetResponse,
    SyncLogRead,
)
from app.services.ingestion_sync import (
    sync_employee, sync_client, sync_project, push_approved_timesheet,
)

router = APIRouter(prefix="/sync", tags=["sync"])
logger = logging.getLogger(__name__)


@router.post("/employees",
             response_model=SyncEmployeeResponse,
             summary="Upsert an employee from the ingestion platform")
async def sync_employee_endpoint(
    body: SyncEmployeeRequest,
    auth: tuple = Depends(get_service_token_tenant),
    session: AsyncSession = Depends(get_db),
):
    tenant_id, _ = auth
    result = await sync_employee(
        session,
        tenant_id=tenant_id,
        ingestion_employee_id=body.ingestion_employee_id,
        full_name=body.full_name,
        email=str(body.email),
        employee_code=body.employee_code,
        reviewer_name=body.reviewer_name,
        payload=body.model_dump(),
    )
    return SyncEmployeeResponse(**result)


@router.post("/clients",
             response_model=SyncClientResponse,
             summary="Upsert a client from the ingestion platform")
async def sync_client_endpoint(
    body: SyncClientRequest,
    auth: tuple = Depends(get_service_token_tenant),
    session: AsyncSession = Depends(get_db),
):
    tenant_id, _ = auth
    result = await sync_client(
        session,
        tenant_id=tenant_id,
        ingestion_client_id=body.ingestion_client_id,
        name=body.name,
        payload=body.model_dump(),
    )
    return SyncClientResponse(**result)


@router.post("/projects",
             response_model=SyncProjectResponse,
             summary="Upsert a project from the ingestion platform")
async def sync_project_endpoint(
    body: SyncProjectRequest,
    auth: tuple = Depends(get_service_token_tenant),
    session: AsyncSession = Depends(get_db),
):
    tenant_id, _ = auth

    # Resolve local client_id from ingestion cross-reference
    result = await session.execute(
        select(Client).where(
            (Client.ingestion_client_id == body.ingestion_client_id) &
            (Client.tenant_id == tenant_id)
        )
    )
    local_client = result.scalar_one_or_none()
    if not local_client:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Client with ingestion_client_id '{body.ingestion_client_id}' "
                "not found in this tenant. Sync the client first."
            ),
        )

    result = await sync_project(
        session,
        tenant_id=tenant_id,
        ingestion_project_id=body.ingestion_project_id,
        client_id=local_client.id,
        name=body.name,
        code=body.code,
        billable_rate=float(body.billable_rate),
        currency=body.currency,
        payload=body.model_dump(),
    )
    return SyncProjectResponse(**result)


@router.post("/timesheets/push",
             response_model=PushTimesheetResponse,
             summary="Push an approved timesheet as APPROVED time entries")
async def push_timesheet_endpoint(
    body: PushTimesheetRequest,
    auth: tuple = Depends(get_service_token_tenant),
    session: AsyncSession = Depends(get_db),
):
    tenant_id, _ = auth
    result = await push_approved_timesheet(
        session,
        tenant_id=tenant_id,
        ingestion_timesheet_id=body.ingestion_timesheet_id,
        ingestion_employee_id=body.ingestion_employee_id,
        ingestion_client_id=body.ingestion_client_id,
        ingestion_project_id=body.ingestion_project_id,
        reviewer_name=body.reviewer_name,
        ingestion_source_tenant=body.ingestion_source_tenant,
        line_items=[item.model_dump() for item in body.line_items],
        payload=body.model_dump(),
    )
    return PushTimesheetResponse(**result)


@router.get("/logs",
            response_model=list[SyncLogRead],
            summary="View sync log for this tenant (via service token)")
async def list_sync_logs(
    auth: tuple = Depends(get_service_token_tenant),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    tenant_id, _ = auth
    result = await session.execute(
        select(SyncLog)
        .where(SyncLog.tenant_id == tenant_id)
        .order_by(SyncLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


@router.get("/health",
            summary="Health check for ingestion platform connection test")
async def sync_health(
    auth: tuple = Depends(get_service_token_tenant),
):
    return {"status": "ok", "app": "timesheet"}


@router.post("/webhook/inbound",
             summary="Receive change notifications from the ingestion platform")
async def receive_webhook(
    request: Request,
    auth: tuple = Depends(get_service_token_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Receives change notifications from the ingestion platform.
    Currently logs all events. Extend this handler to apply changes
    as bidirectional sync requirements grow.

    Expected payload: WebhookEntityChanged schema
    """
    tenant_id, _ = auth
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = body.get("event_type", "unknown")
    logger.info(
        f"Received webhook from ingestion platform: "
        f"tenant={tenant_id} event={event_type}"
    )

    entity_type_map = {
        "client": SyncEntityType.client,
        "project": SyncEntityType.project,
        "user": SyncEntityType.user,
        "employee": SyncEntityType.user,
    }
    entity_prefix = event_type.split(
        ".")[0] if "." in event_type else "unknown"
    entity_type = entity_type_map.get(entity_prefix, SyncEntityType.client)

    log = SyncLog(
        tenant_id=tenant_id,
        direction=SyncDirection.inbound,
        entity_type=entity_type,
        status=SyncStatus.success,
        ingestion_id=body.get("ingestion_id"),
        action=f"webhook:{event_type}",
        payload=json.dumps(body),
    )
    session.add(log)
    await session.commit()

    return {"received": True, "event_type": event_type}
