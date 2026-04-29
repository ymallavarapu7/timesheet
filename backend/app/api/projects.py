from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas import ProjectResponse, ProjectCreate, ProjectUpdate, ProjectWithClient
from app.crud.project import (
    get_project_by_id, create_project, update_project, delete_project,
    list_projects_for_user
)
from app.crud.client import get_client_by_id
from app.core.deps import get_current_user, get_tenant_db, require_role
from app.models.user import User
from app.services.ingestion_sync import _send_outbound_webhook
from app.services.activity import (
    TENANT_ADMIN_ACTIVITY_SCOPE,
    build_activity_event,
    record_activity_events,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectWithClient])
async def list_all_projects(
    client_id: int = Query(None),
    active_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
) -> list:
    """
    List all projects with optional filtering.
    Any authenticated user can view projects within their tenant.
    """
    return await list_projects_for_user(
        db,
        current_user,
        client_id=client_id,
        active_only=active_only,
        skip=skip,
        limit=limit,
    )


@router.get("/{project_id}", response_model=ProjectWithClient)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Get a specific project by ID.
    """
    project = await get_project_by_id(db, project_id, tenant_id=current_user.tenant_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.post("", response_model=ProjectWithClient, status_code=status.HTTP_201_CREATED)
async def create_new_project(
    project_create: ProjectCreate,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> dict:
    """
    Create a new project (Admin only).
    """
    client = await get_client_by_id(db, project_create.client_id, tenant_id=current_user.tenant_id)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Client not found")

    new_project = await create_project(db, project_create, tenant_id=current_user.tenant_id)
    if new_project.tenant_id is not None:
        await record_activity_events(
            db,
            [
                build_activity_event(
                    activity_type="PROJECT_CREATED",
                    visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                    tenant_id=new_project.tenant_id,
                    actor_user=current_user,
                    entity_type="project",
                    entity_id=new_project.id,
                    summary=f"{current_user.full_name} created project {new_project.name}.",
                    route="/client-management",
                    route_params={"clientId": new_project.client_id, "projectId": new_project.id},
                    metadata={"project_name": new_project.name, "client_id": new_project.client_id},
                )
            ],
        )
    return new_project


@router.put("/{project_id}", response_model=ProjectWithClient)
async def update_project_endpoint(
    project_id: int,
    project_update: ProjectUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> dict:
    """
    Update a project (Admin only).
    """
    project = await get_project_by_id(db, project_id, tenant_id=current_user.tenant_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if project_update.client_id:
        client = await get_client_by_id(db, project_update.client_id, tenant_id=current_user.tenant_id)
        if not client:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Client not found")

    # Build changed_fields before updating (for outbound webhook)
    changed_fields = {}
    update_data = project_update.model_dump(exclude_unset=True)
    for field, new_val in update_data.items():
        old_val = getattr(project, field, None)
        if old_val != new_val:
            changed_fields[field] = {"old": old_val, "new": new_val}

    updated_project = await update_project(db, project, project_update)

    if project.ingestion_project_id and changed_fields:
        background_tasks.add_task(
            _send_outbound_webhook,
            tenant_id=current_user.tenant_id,
            event_type="project.updated",
            local_id=project.id,
            ingestion_id=project.ingestion_project_id,
            changed_fields=changed_fields,
            changed_by_name=current_user.full_name,
            session=db,
        )

    return updated_project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_endpoint(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> None:
    """
    Delete a project (Admin only).
    """
    project = await get_project_by_id(db, project_id, tenant_id=current_user.tenant_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    ingestion_project_id = project.ingestion_project_id
    project_id_local = project.id

    success = await delete_project(db, project_id, tenant_id=current_user.tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if ingestion_project_id:
        background_tasks.add_task(
            _send_outbound_webhook,
            tenant_id=current_user.tenant_id,
            event_type="project.deleted",
            local_id=project_id_local,
            ingestion_id=ingestion_project_id,
            changed_fields={},
            changed_by_name=current_user.full_name,
            session=db,
        )
