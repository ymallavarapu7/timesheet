from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from app.models.project import Project
from app.models.user import User, UserRole
from app.models.assignments import UserProjectAccess
from app.schemas import ProjectCreate, ProjectUpdate
from typing import Optional


async def get_project_by_id(db: AsyncSession, project_id: int, tenant_id: Optional[int] = None) -> Optional[Project]:
    """Get project by ID, scoped to a tenant. Pass tenant_id=None only for PLATFORM_ADMIN."""
    query = select(Project).where(Project.id == project_id)
    if tenant_id is not None:
        query = query.where(Project.tenant_id == tenant_id)
    query = query.options(selectinload(Project.client))
    result = await db.execute(query)
    return result.scalars().first()


async def create_project(db: AsyncSession, project_create: ProjectCreate, tenant_id: int) -> Project:
    """Create a new project."""
    db_project = Project(**project_create.model_dump(), tenant_id=tenant_id)
    db.add(db_project)
    try:
        await db.commit()
        await db.refresh(db_project)
    except IntegrityError:
        await db.rollback()
        raise
    return await get_project_by_id(db, db_project.id, tenant_id=tenant_id)


async def update_project(db: AsyncSession, project: Project, project_update: ProjectUpdate) -> Project:
    """Update project fields."""
    update_data = project_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)

    db.add(project)
    await db.commit()
    await db.refresh(project)
    return await get_project_by_id(db, project.id, tenant_id=project.tenant_id)


async def delete_project(db: AsyncSession, project_id: int, tenant_id: Optional[int] = None) -> bool:
    """Delete project by ID, scoped to a tenant."""
    project = await get_project_by_id(db, project_id, tenant_id=tenant_id)
    if project:
        await db.delete(project)
        await db.commit()
        return True
    return False


async def list_projects(db: AsyncSession, tenant_id: int, skip: int = 0, limit: int = 100) -> list[Project]:
    """List all projects for a tenant with pagination."""
    query = select(Project).options(selectinload(Project.client))
    query = query.where(Project.tenant_id == tenant_id)
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def get_assigned_project_ids(db: AsyncSession, user_id: int) -> list[int]:
    result = await db.execute(
        select(UserProjectAccess.project_id).where(
            UserProjectAccess.user_id == user_id)
    )
    return list(result.scalars().all())


async def user_has_project_access(db: AsyncSession, user: User, project_id: int) -> bool:
    if user.role in (UserRole.ADMIN, UserRole.PLATFORM_ADMIN):
        return True

    assigned_project_ids = await get_assigned_project_ids(db, user.id)
    if not assigned_project_ids:
        return True

    return project_id in assigned_project_ids


async def list_projects_for_user(
    db: AsyncSession,
    user: User,
    client_id: Optional[int] = None,
    active_only: bool = False,
    skip: int = 0,
    limit: int = 100,
) -> list[Project]:
    query = select(Project).options(selectinload(Project.client))

    # Always scope to the user's tenant (PLATFORM_ADMIN sees all tenants)
    if user.role != UserRole.PLATFORM_ADMIN:
        query = query.where(Project.tenant_id == user.tenant_id)

    if client_id is not None:
        query = query.where(Project.client_id == client_id)

    if active_only:
        query = query.where(Project.is_active.is_(True))

    if user.role == UserRole.EMPLOYEE:
        assigned_project_ids = await get_assigned_project_ids(db, user.id)
        if assigned_project_ids:
            query = query.where(Project.id.in_(assigned_project_ids))

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def list_projects_by_client(db: AsyncSession, client_id: int, tenant_id: Optional[int] = None) -> list[Project]:
    """List projects by client ID, scoped to a tenant."""
    query = select(Project).where(Project.client_id == client_id)
    if tenant_id is not None:
        query = query.where(Project.tenant_id == tenant_id)
    query = query.options(selectinload(Project.client))
    result = await db.execute(query)
    return result.scalars().all()


async def list_active_projects(db: AsyncSession, tenant_id: int, skip: int = 0, limit: int = 100) -> list[Project]:
    """List all active projects for a tenant with pagination."""
    query = select(Project).where(Project.is_active == True, Project.tenant_id == tenant_id)
    query = query.options(selectinload(Project.client))
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()
