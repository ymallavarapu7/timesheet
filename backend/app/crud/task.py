from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.project import Project
from app.models.task import Task
from app.models.user import User, UserRole
from app.crud.project import get_assigned_project_ids


async def list_tasks_for_user(
    db: AsyncSession,
    user: User,
    project_id: Optional[int] = None,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 500,
) -> list[Task]:
    query = select(Task).options(selectinload(Task.project))

    # Always scope to the user's tenant (PLATFORM_ADMIN sees all tenants)
    if user.role != UserRole.PLATFORM_ADMIN:
        query = query.where(Task.tenant_id == user.tenant_id)

    if project_id is not None:
        query = query.where(Task.project_id == project_id)

    if active_only:
        query = query.where(Task.is_active.is_(True))

    if user.role not in (UserRole.ADMIN, UserRole.PLATFORM_ADMIN):
        assigned_project_ids = await get_assigned_project_ids(db, user.id)
        if assigned_project_ids:
            query = query.where(Task.project_id.in_(assigned_project_ids))

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_task_by_id(db: AsyncSession, task_id: int, tenant_id: Optional[int] = None) -> Optional[Task]:
    """Get task by ID, scoped to a tenant. Pass tenant_id=None only for PLATFORM_ADMIN."""
    query = select(Task).options(selectinload(Task.project)).where(Task.id == task_id)
    if tenant_id is not None:
        query = query.where(Task.tenant_id == tenant_id)
    result = await db.execute(query)
    return result.scalars().first()


async def task_belongs_to_project(
    db: AsyncSession,
    task_id: int,
    project_id: int,
    require_active: bool = True,
) -> bool:
    query = select(Task.id).where(
        (Task.id == task_id) &
        (Task.project_id == project_id)
    )
    if require_active:
        query = query.where(Task.is_active.is_(True))

    result = await db.execute(query)
    return result.scalars().first() is not None


async def create_task(
    db: AsyncSession,
    project_id: int,
    tenant_id: int,
    name: str,
    code: Optional[str] = None,
    description: Optional[str] = None,
    is_active: bool = True,
) -> Task:
    task = Task(
        project_id=project_id,
        tenant_id=tenant_id,
        name=name,
        code=code,
        description=description,
        is_active=is_active,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def update_task(
    db: AsyncSession,
    task: Task,
    name: Optional[str] = None,
    code: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
    project_id: Optional[int] = None,
) -> Task:
    if name is not None:
        task.name = name
    if code is not None:
        task.code = code
    if description is not None:
        task.description = description
    if is_active is not None:
        task.is_active = is_active
    if project_id is not None:
        task.project_id = project_id

    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def delete_task(db: AsyncSession, task: Task) -> None:
    await db.delete(task)
    await db.commit()


async def project_exists(db: AsyncSession, project_id: int, tenant_id: Optional[int] = None) -> bool:
    query = select(Project.id).where(Project.id == project_id)
    if tenant_id is not None:
        query = query.where(Project.tenant_id == tenant_id)
    result = await db.execute(query)
    return result.scalars().first() is not None
