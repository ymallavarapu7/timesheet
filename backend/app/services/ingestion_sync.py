"""
Ingestion Platform Sync Service

Handles all inbound sync operations from the ingestion platform.
Each function is responsible for:
  1. Looking up whether the entity already exists (by ingestion cross-ref ID)
  2. Creating or updating as appropriate
  3. Writing a sync_log record regardless of outcome
  4. Returning a structured result dict

IMPORTANT: These functions bypass normal time entry validation rules
(max hours per day/week, backdate limits) because entries arrive pre-approved
from the ingestion platform's own review workflow.
"""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User, UserRole
from app.models.client import Client
from app.models.project import Project
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.sync_log import SyncLog, SyncDirection, SyncEntityType, SyncStatus
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _write_sync_log(
    session: AsyncSession,
    *,
    tenant_id: int,
    direction: SyncDirection,
    entity_type: SyncEntityType,
    status: SyncStatus,
    local_id: int | None = None,
    ingestion_id: str | None = None,
    action: str | None = None,
    error_message: str | None = None,
    payload: dict | None = None,
) -> None:
    """Write a sync log entry. Never raises — log failures are swallowed."""
    try:
        log_entry = SyncLog(
            tenant_id=tenant_id,
            direction=direction,
            entity_type=entity_type,
            status=status,
            local_id=local_id,
            ingestion_id=ingestion_id,
            action=action,
            error_message=error_message,
            payload=json.dumps(payload, default=lambda o: float(o) if isinstance(o, Decimal) else str(o)) if payload else None,
        )
        session.add(log_entry)
        await session.flush()  # flush but don't commit — caller commits
    except Exception as e:
        logger.error(f"Failed to write sync log: {e}")


async def _get_system_user_id(
    session: AsyncSession, tenant_id: int
) -> int:
    """
    Returns the ID of the system service user for this tenant.
    This user is used as `approved_by` for ingestion-pushed entries.
    Created by the seed script — must exist before sync is used.
    """
    result = await session.execute(
        select(User).where(
            (User.tenant_id == tenant_id) &
            (User.username == f"system_ingestion_{tenant_id}")
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(
            f"System service user for tenant {tenant_id} not found. "
            "Run the seed script to create it."
        )
    return user.id


# ─────────────────────────────────────────────────────────────────────────────
# Employee / User sync
# ─────────────────────────────────────────────────────────────────────────────

async def sync_employee(
    session: AsyncSession,
    *,
    tenant_id: int,
    ingestion_employee_id: str,
    full_name: str,
    email: str,
    employee_code: str | None,
    reviewer_name: str,
    payload: dict,
) -> dict:
    """
    Upsert a user from the ingestion platform.

    Lookup order:
      1. By ingestion_employee_id (most reliable — UUID from ingestion DB)
      2. By email within the tenant (handles cases where user pre-existed)

    If found: update full_name and email if changed.
    If not found: create new EMPLOYEE user with default password.

    Returns: { "action": str, "user_id": int, "status": str }
    """
    action = None
    local_id = None

    try:
        # Lookup by cross-reference ID first
        result = await session.execute(
            select(User).where(
                (User.ingestion_employee_id == ingestion_employee_id) &
                (User.tenant_id == tenant_id)
            )
        )
        user = result.scalar_one_or_none()

        # Fall back to email match within tenant
        if not user:
            result = await session.execute(
                select(User).where(
                    (User.email == email) &
                    (User.tenant_id == tenant_id)
                )
            )
            user = result.scalar_one_or_none()

        if user:
            # Update existing user
            changed = False
            if user.full_name != full_name:
                user.full_name = full_name
                changed = True
            if user.email != email:
                user.email = email
                changed = True
            if user.ingestion_employee_id != ingestion_employee_id:
                user.ingestion_employee_id = ingestion_employee_id
                changed = True
            action = "updated" if changed else "skipped_no_changes"
            local_id = user.id

        else:
            # Create new user
            # Generate username from email (before the @)
            base_username = email.split("@")[0].lower().replace(".", "_")
            # Ensure username uniqueness within tenant
            username = base_username
            suffix = 1
            while True:
                existing = await session.execute(
                    select(User).where(User.username == username)
                )
                if not existing.scalar_one_or_none():
                    break
                username = f"{base_username}_{suffix}"
                suffix += 1

            user = User(
                tenant_id=tenant_id,
                email=email,
                username=username,
                full_name=full_name,
                hashed_password=get_password_hash("password"),
                role=UserRole.EMPLOYEE,
                is_active=True,
                has_changed_password=False,
                ingestion_employee_id=ingestion_employee_id,
                ingestion_created_by=reviewer_name,
            )
            session.add(user)
            await session.flush()  # get user.id
            action = "created"
            local_id = user.id

        await _write_sync_log(
            session,
            tenant_id=tenant_id,
            direction=SyncDirection.inbound,
            entity_type=SyncEntityType.user,
            status=SyncStatus.success,
            local_id=local_id,
            ingestion_id=ingestion_employee_id,
            action=action,
            payload=payload,
        )
        await session.commit()
        return {"action": action, "user_id": local_id, "status": "success"}

    except Exception as e:
        await session.rollback()
        logger.error(f"sync_employee failed: {e}")
        await _write_sync_log(
            session,
            tenant_id=tenant_id,
            direction=SyncDirection.inbound,
            entity_type=SyncEntityType.user,
            status=SyncStatus.failed,
            ingestion_id=ingestion_employee_id,
            action=action,
            error_message=str(e),
            payload=payload,
        )
        await session.commit()
        return {"action": action, "status": "failed", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Client sync
# ─────────────────────────────────────────────────────────────────────────────

async def sync_client(
    session: AsyncSession,
    *,
    tenant_id: int,
    ingestion_client_id: str,
    name: str,
    payload: dict,
) -> dict:
    """
    Upsert a client from the ingestion platform.

    Lookup order:
      1. By ingestion_client_id
      2. By name within tenant (case-insensitive)

    Returns: { "action": str, "client_id": int, "status": str }
    """
    action = None
    local_id = None

    try:
        result = await session.execute(
            select(Client).where(
                (Client.ingestion_client_id == ingestion_client_id) &
                (Client.tenant_id == tenant_id)
            )
        )
        client = result.scalar_one_or_none()

        if not client:
            # Try name match (case-insensitive)
            result = await session.execute(
                select(Client).where(
                    (Client.name.ilike(name)) &
                    (Client.tenant_id == tenant_id)
                )
            )
            client = result.scalar_one_or_none()

        if client:
            changed = False
            if client.name != name:
                client.name = name
                changed = True
            if client.ingestion_client_id != ingestion_client_id:
                client.ingestion_client_id = ingestion_client_id
                changed = True
            action = "updated" if changed else "skipped_no_changes"
            local_id = client.id
        else:
            client = Client(
                tenant_id=tenant_id,
                name=name,
                ingestion_client_id=ingestion_client_id,
            )
            session.add(client)
            await session.flush()
            action = "created"
            local_id = client.id

        await _write_sync_log(
            session,
            tenant_id=tenant_id,
            direction=SyncDirection.inbound,
            entity_type=SyncEntityType.client,
            status=SyncStatus.success,
            local_id=local_id,
            ingestion_id=ingestion_client_id,
            action=action,
            payload=payload,
        )
        await session.commit()
        return {"action": action, "client_id": local_id, "status": "success"}

    except Exception as e:
        await session.rollback()
        logger.error(f"sync_client failed: {e}")
        await _write_sync_log(
            session,
            tenant_id=tenant_id,
            direction=SyncDirection.inbound,
            entity_type=SyncEntityType.client,
            status=SyncStatus.failed,
            ingestion_id=ingestion_client_id,
            error_message=str(e),
            payload=payload,
        )
        await session.commit()
        return {"action": action, "status": "failed", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Project sync
# ─────────────────────────────────────────────────────────────────────────────

async def sync_project(
    session: AsyncSession,
    *,
    tenant_id: int,
    ingestion_project_id: str,
    client_id: int,           # local timesheet app client_id (resolved by caller)
    name: str,
    code: str | None,
    billable_rate: float,
    currency: str | None,
    payload: dict,
) -> dict:
    """
    Upsert a project from the ingestion platform.

    Lookup order:
      1. By ingestion_project_id
      2. By (client_id, code) if code is provided
      3. By (client_id, name) — case-insensitive

    Conflict resolution: last-write-wins for billable_rate and name.

    Returns: { "action": str, "project_id": int, "status": str }
    """
    action = None
    local_id = None

    try:
        result = await session.execute(
            select(Project).where(
                (Project.ingestion_project_id == ingestion_project_id) &
                (Project.tenant_id == tenant_id)
            )
        )
        project = result.scalar_one_or_none()

        if not project and code:
            result = await session.execute(
                select(Project).where(
                    (Project.client_id == client_id) &
                    (Project.code == code) &
                    (Project.tenant_id == tenant_id)
                )
            )
            project = result.scalar_one_or_none()

        if not project:
            result = await session.execute(
                select(Project).where(
                    (Project.client_id == client_id) &
                    (Project.name.ilike(name)) &
                    (Project.tenant_id == tenant_id)
                )
            )
            project = result.scalar_one_or_none()

        if project:
            changed = False
            if project.name != name:
                project.name = name
                changed = True
            if float(project.billable_rate) != float(billable_rate):
                project.billable_rate = billable_rate
                changed = True
            if code and project.code != code:
                project.code = code
                changed = True
            if project.ingestion_project_id != ingestion_project_id:
                project.ingestion_project_id = ingestion_project_id
                changed = True
            action = "updated" if changed else "skipped_no_changes"
            local_id = project.id
        else:
            project = Project(
                tenant_id=tenant_id,
                client_id=client_id,
                name=name,
                code=code,
                billable_rate=billable_rate,
                currency=currency or "USD",
                is_active=True,
                ingestion_project_id=ingestion_project_id,
            )
            session.add(project)
            await session.flush()
            action = "created"
            local_id = project.id

        await _write_sync_log(
            session,
            tenant_id=tenant_id,
            direction=SyncDirection.inbound,
            entity_type=SyncEntityType.project,
            status=SyncStatus.success,
            local_id=local_id,
            ingestion_id=ingestion_project_id,
            action=action,
            payload=payload,
        )
        await session.commit()
        return {"action": action, "project_id": local_id, "status": "success"}

    except Exception as e:
        await session.rollback()
        logger.error(f"sync_project failed: {e}")
        await _write_sync_log(
            session,
            tenant_id=tenant_id,
            direction=SyncDirection.inbound,
            entity_type=SyncEntityType.project,
            status=SyncStatus.failed,
            ingestion_id=ingestion_project_id,
            error_message=str(e),
            payload=payload,
        )
        await session.commit()
        return {"action": action, "status": "failed", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Timesheet push (core operation)
# ─────────────────────────────────────────────────────────────────────────────

async def push_approved_timesheet(
    session: AsyncSession,
    *,
    tenant_id: int,
    ingestion_timesheet_id: str,
    ingestion_employee_id: str,
    ingestion_client_id: str,
    ingestion_project_id: str,
    reviewer_name: str,
    ingestion_source_tenant: str,
    line_items: list[dict],
    payload: dict,
) -> dict:
    """
    Push an approved timesheet from the ingestion platform as APPROVED
    time entries in this application.

    Pre-conditions (enforced before calling this function):
      - Employee, client, and project have already been synced via
        sync_employee(), sync_client(), sync_project() — their local IDs
        are resolved by looking up cross-reference columns.

    Each line item in line_items must have:
      { ingestion_line_item_id, work_date, hours, description }

    Behaviour per line item:
      - If ingestion_line_item_id already exists in time_entries
        (duplicate push): skip with action='skipped_duplicate'
      - Otherwise: create as APPROVED, bypassing hour validation limits

    approved_by is set to the system service user for this tenant.
    ingestion_approved_by_name stores the human reviewer name as text.

    Returns summary:
      {
        "status": "success" | "partial" | "failed",
        "created": int,
        "skipped": int,
        "failed": int,
        "line_item_results": [ { ingestion_line_item_id, action, error? } ]
      }
    """
    now = datetime.now(timezone.utc)
    results = []
    created_count = 0
    skipped_count = 0
    failed_count = 0

    try:
        system_user_id = await _get_system_user_id(session, tenant_id)
    except ValueError as e:
        await _write_sync_log(
            session,
            tenant_id=tenant_id,
            direction=SyncDirection.inbound,
            entity_type=SyncEntityType.timesheet,
            status=SyncStatus.failed,
            ingestion_id=ingestion_timesheet_id,
            action="failed_no_system_user",
            error_message=str(e),
            payload=payload,
        )
        await session.commit()
        return {"status": "failed", "error": str(e), "created": 0, "skipped": 0, "failed": 0, "line_item_results": []}

    # Resolve local IDs from cross-reference columns
    user_result = await session.execute(
        select(User).where(
            (User.ingestion_employee_id == ingestion_employee_id) &
            (User.tenant_id == tenant_id)
        )
    )
    local_user = user_result.scalar_one_or_none()

    project_result = await session.execute(
        select(Project).where(
            (Project.ingestion_project_id == ingestion_project_id) &
            (Project.tenant_id == tenant_id)
        )
    )
    local_project = project_result.scalar_one_or_none()

    if not local_user or not local_project:
        missing = []
        if not local_user:
            missing.append(f"employee {ingestion_employee_id}")
        if not local_project:
            missing.append(f"project {ingestion_project_id}")
        error_msg = (
            f"Cannot push timesheet: missing local records for {', '.join(missing)}. "
            "Sync employee, client, and project first."
        )
        await _write_sync_log(
            session,
            tenant_id=tenant_id,
            direction=SyncDirection.inbound,
            entity_type=SyncEntityType.timesheet,
            status=SyncStatus.failed,
            ingestion_id=ingestion_timesheet_id,
            action="failed_missing_references",
            error_message=error_msg,
            payload=payload,
        )
        await session.commit()
        return {"status": "failed", "error": error_msg, "created": 0, "skipped": 0, "failed": 0, "line_item_results": []}

    # Process each line item
    for item in line_items:
        line_item_id = item.get("ingestion_line_item_id")
        try:
            # Deduplication check
            existing = await session.execute(
                select(TimeEntry).where(
                    TimeEntry.ingestion_line_item_id == line_item_id
                )
            )
            if existing.scalar_one_or_none():
                results.append({
                    "ingestion_line_item_id": line_item_id,
                    "action": "skipped_duplicate",
                })
                skipped_count += 1
                continue

            # Parse work_date
            work_date = datetime.strptime(
                item["work_date"], "%Y-%m-%d"
            ).date()

            # Create time entry as APPROVED
            # NOTE: Hour validation (max 12/day, 60/week) is intentionally
            # bypassed for ingestion-pushed entries. The ingestion platform's
            # own review process is the source of validation for these entries.
            entry = TimeEntry(
                tenant_id=tenant_id,
                user_id=local_user.id,
                project_id=local_project.id,
                task_id=None,           # tasks not extracted by ingestion platform
                entry_date=work_date,
                hours=item["hours"],
                description=item.get("description") or "",
                is_billable=True,       # ingestion entries are always billable
                status=TimeEntryStatus.APPROVED,
                submitted_at=now,
                approved_by=system_user_id,
                approved_at=now,
                created_by=system_user_id,
                updated_by=system_user_id,
                ingestion_timesheet_id=ingestion_timesheet_id,
                ingestion_line_item_id=line_item_id,
                ingestion_approved_by_name=reviewer_name,
                ingestion_source_tenant=ingestion_source_tenant,
            )
            session.add(entry)
            await session.flush()

            results.append({
                "ingestion_line_item_id": line_item_id,
                "action": "created",
                "time_entry_id": entry.id,
            })
            created_count += 1

        except Exception as e:
            logger.error(
                f"Failed to create time entry for line item {line_item_id}: {e}"
            )
            results.append({
                "ingestion_line_item_id": line_item_id,
                "action": "failed",
                "error": str(e),
            })
            failed_count += 1

    # Determine overall status
    if failed_count == 0 and created_count > 0:
        overall_status = SyncStatus.success
    elif failed_count == 0 and created_count == 0:
        overall_status = SyncStatus.skipped
    elif failed_count > 0 and created_count > 0:
        overall_status = SyncStatus.partial
    else:
        overall_status = SyncStatus.failed

    await _write_sync_log(
        session,
        tenant_id=tenant_id,
        direction=SyncDirection.inbound,
        entity_type=SyncEntityType.timesheet,
        status=overall_status,
        ingestion_id=ingestion_timesheet_id,
        action=f"created:{created_count} skipped:{skipped_count} failed:{failed_count}",
        payload=payload,
    )
    await session.commit()

    return {
        "status": overall_status.value,
        "created": created_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "line_item_results": results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Outbound webhook
# ─────────────────────────────────────────────────────────────────────────────

async def _send_outbound_webhook(
    *,
    tenant_id: int,
    event_type: str,
    local_id: int,
    ingestion_id: str | None,
    changed_fields: dict,
    changed_by_name: str | None,
    session: AsyncSession,
) -> None:
    """
    Fire-and-forget outbound webhook to the ingestion platform.
    Logs success or failure to sync_log. Never raises.
    """
    import httpx
    from app.core.config import settings

    if not settings.ingestion_platform_url or not settings.ingestion_service_token:
        logger.debug("Outbound webhook skipped: INGESTION_PLATFORM_URL not configured")
        return

    payload = {
        "event_type": event_type,
        "tenant_id": tenant_id,
        "local_id": local_id,
        "ingestion_id": ingestion_id,
        "changed_fields": changed_fields,
        "changed_at": datetime.now(timezone.utc).isoformat(),
        "changed_by_name": changed_by_name,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{settings.ingestion_platform_url}/api/sync/webhook/inbound",
                json=payload,
                headers={
                    "X-Service-Token": settings.ingestion_service_token,
                    "X-Tenant-ID": str(tenant_id),
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()

        status_val = SyncStatus.success
        error_msg = None
    except Exception as e:
        logger.warning(f"Outbound webhook failed ({event_type}): {e}")
        status_val = SyncStatus.failed
        error_msg = str(e)

    # Map event_type prefix to SyncEntityType
    entity_prefix = event_type.split(".")[0] if "." in event_type else "client"
    entity_type_map = {
        "client": SyncEntityType.client,
        "project": SyncEntityType.project,
        "user": SyncEntityType.user,
    }
    entity_type = entity_type_map.get(entity_prefix, SyncEntityType.client)

    await _write_sync_log(
        session,
        tenant_id=tenant_id,
        direction=SyncDirection.outbound,
        entity_type=entity_type,
        status=status_val,
        local_id=local_id,
        ingestion_id=ingestion_id,
        action=f"webhook:{event_type}",
        error_message=error_msg,
        payload=payload,
    )
    # Note: do not commit here — caller commits
