from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db import get_db
from app.models.department import Department
from app.models.user import User
from app.schemas import DepartmentCreate, DepartmentResponse

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("", response_model=list[DepartmentResponse])
async def list_departments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Department]:
    """Any authenticated user can read the tenant's department list (used in dropdowns)."""
    if current_user.tenant_id is None:
        return []
    result = await db.execute(
        select(Department)
        .where(Department.tenant_id == current_user.tenant_id)
        .order_by(Department.name.asc())
    )
    return list(result.scalars().all())


@router.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    body: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> Department:
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant context required")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name cannot be empty")
    dept = Department(tenant_id=current_user.tenant_id, name=name)
    db.add(dept)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Department with that name already exists")
    await db.refresh(dept)
    return dept


@router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(
    department_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN")),
) -> None:
    result = await db.execute(
        select(Department).where(Department.id == department_id)
    )
    dept = result.scalar_one_or_none()
    if dept is None or dept.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    await db.delete(dept)
    await db.commit()
