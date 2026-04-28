from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ingested_email import IngestedEmail
from app.models.ingestion_timesheet import (
    IngestionAuditActorType,
    IngestionAuditLog,
    IngestionTimesheet,
)


async def get_ingestion_timesheet(
    session: AsyncSession,
    timesheet_id: int,
    tenant_id: int,
) -> IngestionTimesheet | None:
    result = await session.execute(
        select(IngestionTimesheet)
        .where(
            (IngestionTimesheet.id == timesheet_id) &
            (IngestionTimesheet.tenant_id == tenant_id)
        )
        .options(
            selectinload(IngestionTimesheet.line_items),
            selectinload(IngestionTimesheet.audit_log),
            selectinload(IngestionTimesheet.email).selectinload(IngestedEmail.attachments),
            selectinload(IngestionTimesheet.employee),
            selectinload(IngestionTimesheet.client),
            selectinload(IngestionTimesheet.supervisor),
        )
    )
    return result.scalar_one_or_none()


async def list_ingestion_timesheets(
    session: AsyncSession,
    tenant_id: int,
    status: str | None = None,
    client_id: int | None = None,
    employee_id: int | None = None,
    email_id: int | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[IngestionTimesheet]:
    query = (
        select(IngestionTimesheet)
        .join(IngestionTimesheet.email)
        .where(IngestionTimesheet.tenant_id == tenant_id)
        .options(
            selectinload(IngestionTimesheet.employee),
            selectinload(IngestionTimesheet.client),
            selectinload(IngestionTimesheet.email),
            selectinload(IngestionTimesheet.supervisor),
        )
        .order_by(IngestionTimesheet.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status:
        query = query.where(IngestionTimesheet.status == status)
    if client_id:
        query = query.where(IngestionTimesheet.client_id == client_id)
    if employee_id:
        query = query.where(IngestionTimesheet.employee_id == employee_id)
    if email_id:
        query = query.where(IngestionTimesheet.email_id == email_id)
    if search:
        like_value = f"%{search.strip()}%"
        query = query.where(
            (IngestionTimesheet.llm_summary.ilike(like_value)) |
            (IngestedEmail.subject.ilike(like_value)) |
            (IngestedEmail.sender_email.ilike(like_value))
        )

    result = await session.execute(query)
    return list(result.scalars().all())


async def write_audit_log(
    session: AsyncSession,
    timesheet_id: int,
    user_id: int | None,
    action: str,
    actor_type: IngestionAuditActorType = IngestionAuditActorType.user,
    previous_value: dict | None = None,
    new_value: dict | None = None,
    comment: str | None = None,
) -> None:
    entry = IngestionAuditLog(
        ingestion_timesheet_id=timesheet_id,
        user_id=user_id,
        action=action,
        actor_type=actor_type,
        previous_value=previous_value,
        new_value=new_value,
        comment=comment,
        created_at=datetime.now(timezone.utc),
    )
    session.add(entry)
