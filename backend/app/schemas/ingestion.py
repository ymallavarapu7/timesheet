from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.ingestion_timesheet import IngestionTimesheetStatus
from app.models.mailbox import MailboxAuthType, MailboxProtocol, OAuthProvider


class MailboxCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    protocol: MailboxProtocol
    auth_type: MailboxAuthType = MailboxAuthType.basic
    host: str | None = None
    port: int | None = None
    use_ssl: bool = True
    username: str | None = None
    password: str | None = None
    oauth_provider: OAuthProvider | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    linked_client_id: int | None = None

    @field_validator("host")
    @classmethod
    def host_required_for_basic(cls, value: str | None, info) -> str | None:
        if info.data.get("auth_type") == MailboxAuthType.basic and not value:
            raise ValueError("host is required for basic auth mailboxes")
        return value


class MailboxUpdate(BaseModel):
    label: str | None = None
    host: str | None = None
    port: int | None = None
    use_ssl: bool | None = None
    username: str | None = None
    password: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    linked_client_id: int | None = None
    is_active: bool | None = None


class MailboxRead(BaseModel):
    id: int
    tenant_id: int
    label: str
    protocol: str
    auth_type: str
    host: str | None
    port: int | None
    use_ssl: bool
    username: str | None
    has_password: bool
    oauth_provider: str | None
    oauth_email: EmailStr | None = None
    smtp_host: str | None
    smtp_port: int | None
    smtp_username: str | None
    linked_client_id: int | None
    is_active: bool
    last_fetched_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OAuthConnectResponse(BaseModel):
    auth_url: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str
    provider: str


class ConnectionTestResult(BaseModel):
    success: bool
    error: str | None = None
    latency_ms: int
    message_count: int = 0


class FetchJobResponse(BaseModel):
    job_id: str
    status: str = "queued"
    message: str | None = None


class FetchJobStatus(BaseModel):
    status: str
    job_id: str
    progress: int | None = None
    message: str | None = None
    tenant_id: int | None = None
    mode: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class ReprocessSkippedResponse(BaseModel):
    job_id: str
    status: str = "queued"
    deleted_emails: int
    deleted_attachments: int
    deleted_files: int
    file_delete_errors: int = 0


class CleanupSkippedNoiseResponse(BaseModel):
    scanned_emails: int
    deleted_emails: int
    deleted_attachments: int
    deleted_files: int
    file_delete_errors: int = 0


class ReprocessStoredEmailRequest(BaseModel):
    email_id: int
    attachment_ids: list[int] | None = None


class ReprocessStoredEmailResponse(BaseModel):
    job_id: str
    status: str = "queued"
    mode: str
    email_id: int


class LineItemRead(BaseModel):
    id: int
    work_date: date
    hours: Decimal
    description: str | None
    project_code: str | None
    project_id: int | None
    is_corrected: bool
    original_value: dict[str, Any] | None
    is_rejected: bool = False
    rejection_reason: str | None = None

    model_config = {"from_attributes": True}


class LineItemUpdate(BaseModel):
    work_date: date | None = None
    hours: Decimal | None = None
    description: str | None = None
    project_code: str | None = None
    project_id: int | None = None


class LineItemCreate(BaseModel):
    work_date: date
    hours: Decimal = Field(..., gt=0)
    description: str | None = None
    project_code: str | None = None
    project_id: int | None = None


class IngestionTimesheetSummary(BaseModel):
    id: int
    tenant_id: int
    email_id: int
    attachment_id: int | None = None
    subject: str | None = None
    sender_email: str | None = None
    sender_name: str | None = None
    employee_id: int | None
    employee_name: str | None
    extracted_employee_name: str | None = None
    extracted_supervisor_name: str | None = None
    supervisor_user_id: int | None = None
    supervisor_name: str | None = None
    client_id: int | None
    client_name: str | None
    period_start: date | None
    period_end: date | None
    total_hours: Decimal | None
    status: str
    push_status: str | None = None
    time_entries_created: bool = False
    llm_anomalies: list[dict[str, Any]] | None = None
    received_at: datetime | None = None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SkippedEmailRead(BaseModel):
    id: int
    subject: str | None
    sender_email: str
    sender_name: str | None = None
    received_at: datetime | None
    mailbox_label: str | None = None
    has_attachments: bool
    timesheet_attachment_count: int = 0
    classification_intent: str | None = None
    skip_reason: str | None = None
    skip_detail: str | None = None
    reprocessable_attachments: list[dict[str, Any]] = Field(default_factory=list)


class SkippedEmailOverview(BaseModel):
    count: int
    emails: list[SkippedEmailRead]


class EmailContextRead(BaseModel):
    id: int
    subject: str | None
    sender_email: str
    sender_name: str | None
    forwarded_from_email: str | None = None
    forwarded_from_name: str | None = None
    recipients: Any | None
    body_text: str | None
    body_html: str | None
    received_at: datetime | None
    attachments: list[dict[str, Any]]

    model_config = {"from_attributes": True}


class StoredEmailDetail(BaseModel):
    id: int
    subject: str | None
    sender_email: str
    sender_name: str | None
    forwarded_from_email: str | None = None
    forwarded_from_name: str | None = None
    recipients: Any | None
    body_text: str | None
    body_html: str | None
    received_at: datetime | None
    mailbox_label: str | None = None
    classification_intent: str | None = None
    skip_reason: str | None = None
    skip_detail: str | None = None
    llm_classification: dict[str, Any] | None = None
    attachments: list[dict[str, Any]]


class IngestionTimesheetDetail(BaseModel):
    id: int
    tenant_id: int
    attachment_id: int | None = None
    status: str
    employee_id: int | None
    employee_name: str | None
    client_id: int | None
    client_name: str | None
    reviewer_id: int | None
    period_start: date | None
    period_end: date | None
    total_hours: Decimal | None
    extracted_data: dict[str, Any] | None
    corrected_data: dict[str, Any] | None
    llm_anomalies: list[dict[str, Any]] | None = None
    llm_match_suggestions: dict[str, Any] | None
    llm_summary: str | None
    rejection_reason: str | None
    internal_notes: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    time_entries_created: bool
    extracted_employee_name: str | None = None
    extracted_supervisor_name: str | None = None
    supervisor_user_id: int | None = None
    supervisor_name: str | None = None
    email: EmailContextRead | None
    line_items: list[LineItemRead]
    audit_log: list[dict[str, Any]]

    model_config = {"from_attributes": True}


class TimesheetDataUpdate(BaseModel):
    employee_id: int | None = None
    client_id: int | None = None
    # Reviewer-confirmed supervisor (permissive: any reviewer can override
    # the LLM-extracted name). Set to None or omit to clear; the original
    # extracted_supervisor_name is preserved on the record regardless.
    supervisor_user_id: int | None = None
    period_start: date | None = None
    period_end: date | None = None
    total_hours: Decimal | None = None
    internal_notes: str | None = None


class ApproveRequest(BaseModel):
    comment: str | None = None


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    comment: str | None = None


class HoldRequest(BaseModel):
    comment: str | None = None


class AssignChainCandidateRequest(BaseModel):
    """
    Request body for POST /ingestion/timesheets/{id}/assign-chain-candidate.

    At least one of `name` or `email` must be provided. When both are given,
    the endpoint prefers `email` for user lookup (exact match) and uses
    `name` as the fuzzy-match fallback. When only `name` is given (the
    reviewer picked a name-only chain entry and chose not to type an
    email), the endpoint still creates or reuses a user — email may be
    left blank on the created row.
    """
    name: str | None = None
    email: str | None = None


class AssignChainCandidateResponse(BaseModel):
    timesheet_id: int
    employee_id: int
    created_new_user: bool


class DraftCommentRequest(BaseModel):
    seed_text: str = ""


class DraftCommentResponse(BaseModel):
    draft: str


class ApprovalResult(BaseModel):
    ingestion_timesheet_id: int
    time_entries_created: int
    employee_id: int
    project_ids: list[int]
    status: str = "approved"
    overlapping_entries_count: int = 0
    overlapping_dates: list[str] = []


class MappingReapplyResult(BaseModel):
    checked: int
    updated: int
