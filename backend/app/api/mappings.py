from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_ingestion_enabled, require_role
from app.db import get_db
from app.models.client import Client
from app.models.email_sender_mapping import EmailSenderMapping
from app.models.user import User
from app.schemas.ingestion import MappingCreate, MappingRead, MappingUpdate

router = APIRouter(prefix="/mappings", tags=["mappings"])


async def _validate_mapping_refs(
    session: AsyncSession,
    current_user: User,
    client_id: int | None,
    employee_id: int | None,
) -> None:
    if client_id is not None:
        client = await session.get(Client, client_id)
        if not client:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Client not found")
        if client.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: client belongs to a different tenant",
            )

    if employee_id is not None:
        employee = await session.get(User, employee_id)
        if not employee:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Employee not found")
        if employee.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: employee belongs to a different tenant",
            )


@router.get("", response_model=list[MappingRead])
async def list_mappings(
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> list[EmailSenderMapping]:
    result = await session.execute(
        select(EmailSenderMapping)
        .where(EmailSenderMapping.tenant_id == current_user.tenant_id)
        .order_by(EmailSenderMapping.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=MappingRead, status_code=status.HTTP_201_CREATED)
async def create_mapping(
    body: MappingCreate,
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> EmailSenderMapping:
    await _validate_mapping_refs(session, current_user, body.client_id, body.employee_id)
    mapping = EmailSenderMapping(
        tenant_id=current_user.tenant_id,
        match_type=body.match_type,
        match_value=body.match_value.lower().strip(),
        client_id=body.client_id,
        employee_id=body.employee_id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return mapping


@router.patch("/{mapping_id}", response_model=MappingRead)
async def update_mapping(
    mapping_id: int,
    body: MappingUpdate,
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> EmailSenderMapping:
    result = await session.execute(
        select(EmailSenderMapping).where(
            (EmailSenderMapping.id == mapping_id) &
            (EmailSenderMapping.tenant_id == current_user.tenant_id)
        )
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")

    updates = body.model_dump(exclude_unset=True)
    await _validate_mapping_refs(
        session,
        current_user,
        updates.get("client_id", mapping.client_id),
        updates.get("employee_id", mapping.employee_id),
    )
    if "match_value" in updates and updates["match_value"] is not None:
        updates["match_value"] = updates["match_value"].lower().strip()
    for key, value in updates.items():
        setattr(mapping, key, value)

    await session.commit()
    await session.refresh(mapping)
    return mapping


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mapping(
    mapping_id: int,
    current_user=Depends(require_role("ADMIN")),
    _: object = Depends(require_ingestion_enabled),
    session: AsyncSession = Depends(get_db),
) -> None:
    result = await session.execute(
        select(EmailSenderMapping).where(
            (EmailSenderMapping.id == mapping_id) &
            (EmailSenderMapping.tenant_id == current_user.tenant_id)
        )
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    await session.delete(mapping)
    await session.commit()
