from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_tenant_db, require_role
from app.crud.task import (
    create_task,
    delete_task,
    get_task_by_id,
    list_tasks_for_user,
    project_exists,
    update_task,
)
from app.crud.project import get_project_by_id
from app.models.user import User
from app.schemas import TaskCreate, TaskResponse, TaskUpdate, TaskWithProject
from app.services.activity import (
    TENANT_ADMIN_ACTIVITY_SCOPE,
    build_activity_event,
    record_activity_events,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskWithProject])
async def list_tasks(
    project_id: Optional[int] = Query(None),
    active_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    return await list_tasks_for_user(
        db,
        current_user,
        project_id=project_id,
        active_only=active_only,
        skip=skip,
        limit=limit,
    )


@router.get("/{task_id}", response_model=TaskWithProject)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    task = await get_task_by_id(db, task_id, tenant_id=current_user.tenant_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    tasks = await list_tasks_for_user(
        db,
        current_user,
        project_id=task.project_id,
        active_only=False,
        skip=0,
        limit=1,
    )
    if not tasks and current_user.role.value not in ("ADMIN", "PLATFORM_ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return task


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task_endpoint(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
):
    project = await get_project_by_id(db, payload.project_id, tenant_id=current_user.tenant_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Project not found")

    new_task = await create_task(
        db,
        project_id=payload.project_id,
        tenant_id=current_user.tenant_id,
        name=payload.name,
        code=payload.code,
        description=payload.description,
        is_active=payload.is_active,
    )
    if new_task.tenant_id is not None:
        await record_activity_events(
            db,
            [
                build_activity_event(
                    activity_type="TASK_CREATED",
                    visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                    tenant_id=new_task.tenant_id,
                    actor_user=current_user,
                    entity_type="task",
                    entity_id=new_task.id,
                    summary=f"{current_user.full_name} created task {new_task.name}.",
                    route="/tasks",
                    route_params={"taskId": new_task.id},
                    metadata={"task_name": new_task.name},
                )
            ],
        )
    return new_task


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task_endpoint(
    task_id: int,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
):
    task = await get_task_by_id(db, task_id, tenant_id=current_user.tenant_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if payload.project_id is not None:
        project = await get_project_by_id(db, payload.project_id, tenant_id=current_user.tenant_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Project not found")

    updated_task = await update_task(
        db,
        task,
        name=payload.name,
        code=payload.code,
        description=payload.description,
        is_active=payload.is_active,
        project_id=payload.project_id,
    )
    if updated_task.tenant_id is not None:
        await record_activity_events(
            db,
            [
                build_activity_event(
                    activity_type="TASK_UPDATED",
                    visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                    tenant_id=updated_task.tenant_id,
                    actor_user=current_user,
                    entity_type="task",
                    entity_id=updated_task.id,
                    summary=f"{current_user.full_name} updated task {updated_task.name}.",
                    route="/tasks",
                    route_params={"taskId": updated_task.id},
                    metadata={"task_name": updated_task.name},
                )
            ],
        )
    return updated_task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_endpoint(
    task_id: int,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
):
    task = await get_task_by_id(db, task_id, tenant_id=current_user.tenant_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    task_name = task.name
    task_tenant_id = task.tenant_id
    task_id_local = task.id

    await delete_task(db, task)

    if task_tenant_id is not None:
        await record_activity_events(
            db,
            [
                build_activity_event(
                    activity_type="TASK_DELETED",
                    visibility_scope=TENANT_ADMIN_ACTIVITY_SCOPE,
                    tenant_id=task_tenant_id,
                    actor_user=current_user,
                    entity_type="task",
                    entity_id=task_id_local,
                    summary=f"{current_user.full_name} deleted task {task_name}.",
                    route="/tasks",
                    route_params={"taskId": task_id_local},
                    metadata={"task_name": task_name},
                )
            ],
        )
