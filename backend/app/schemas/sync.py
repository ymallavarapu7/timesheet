from pydantic import BaseModel, Field
from datetime import datetime
from decimal import Decimal


# ── Service token schemas ─────────────────────────────────────────────────────

class ServiceTokenCreate(BaseModel):
    name: str = Field(..., description="Human-readable label for this token")
    issuer: str = Field(..., description="Identifying name of the calling system")


class ServiceTokenRead(BaseModel):
    id: int
    name: str
    tenant_id: int
    issuer: str
    is_active: bool
    last_used_at: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ServiceTokenCreatedResponse(ServiceTokenRead):
    token: str = Field(..., description="Plaintext token — shown once only")


# ── Sync payload schemas (inbound from ingestion platform) ───────────────────

class SyncEmployeeRequest(BaseModel):
    ingestion_employee_id: str = Field(..., description="UUID from ingestion employees table")
    full_name: str
    email: str
    employee_code: str | None = None
    reviewer_name: str = Field(..., description="Name of ingestion reviewer triggering this sync")


class SyncClientRequest(BaseModel):
    ingestion_client_id: str = Field(..., description="UUID from ingestion clients table")
    name: str


class SyncProjectRequest(BaseModel):
    ingestion_project_id: str = Field(..., description="UUID from ingestion projects table")
    ingestion_client_id: str = Field(..., description="UUID — used to resolve local client_id")
    name: str
    code: str | None = None
    billable_rate: Decimal = Field(..., ge=0)
    currency: str | None = "USD"


class LineItemRequest(BaseModel):
    ingestion_line_item_id: str = Field(..., description="UUID from ingestion timesheet_line_items")
    work_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$",
                           description="ISO 8601 date: YYYY-MM-DD")
    hours: Decimal = Field(..., gt=0)
    description: str | None = None


class PushTimesheetRequest(BaseModel):
    ingestion_timesheet_id: str
    ingestion_employee_id: str
    ingestion_client_id: str
    ingestion_project_id: str
    reviewer_name: str = Field(...,
        description="Name of the ingestion reviewer who approved this timesheet")
    ingestion_source_tenant: str = Field(...,
        description="Slug or name of the ingestion platform tenant")
    line_items: list[LineItemRequest] = Field(..., min_length=1)


# ── Sync response schemas ─────────────────────────────────────────────────────

class SyncEmployeeResponse(BaseModel):
    action: str | None
    user_id: int | None = None
    status: str
    error: str | None = None


class SyncClientResponse(BaseModel):
    action: str | None
    client_id: int | None = None
    status: str
    error: str | None = None


class SyncProjectResponse(BaseModel):
    action: str | None
    project_id: int | None = None
    status: str
    error: str | None = None


class LineItemResult(BaseModel):
    ingestion_line_item_id: str
    action: str
    time_entry_id: int | None = None
    error: str | None = None


class PushTimesheetResponse(BaseModel):
    status: str
    created: int = 0
    skipped: int = 0
    failed: int = 0
    line_item_results: list[LineItemResult] = []
    error: str | None = None


# ── Outbound webhook payload schemas ─────────────────────────────────────────

class WebhookEntityChanged(BaseModel):
    """
    Sent by this app to the ingestion platform when a shared entity changes.
    """
    event_type: str  # e.g. 'client.updated', 'project.updated', 'user.deactivated'
    tenant_id: int
    local_id: int
    ingestion_id: str | None    # cross-reference UUID if known
    changed_fields: dict        # { field_name: { old: value, new: value } }
    changed_at: datetime
    changed_by_name: str | None  # name of user who made the change


# ── Sync log read schema ──────────────────────────────────────────────────────

class SyncLogRead(BaseModel):
    id: int
    tenant_id: int
    direction: str
    entity_type: str
    local_id: int | None
    ingestion_id: str | None
    status: str
    action: str | None
    error_message: str | None
    created_at: datetime

    class Config:
        from_attributes = True
