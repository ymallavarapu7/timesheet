from pydantic import BaseModel, EmailStr, Field
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Optional, List
from enum import Enum


class UserRole(str, Enum):
    """User role enumeration."""
    EMPLOYEE = "EMPLOYEE"
    MANAGER = "MANAGER"
    SENIOR_MANAGER = "SENIOR_MANAGER"
    CEO = "CEO"
    ADMIN = "ADMIN"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"


class TimeEntryStatus(str, Enum):
    """TimeEntry status enumeration."""
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TimeOffType(str, Enum):
    SICK_DAY = "SICK_DAY"
    PTO = "PTO"
    HALF_DAY = "HALF_DAY"
    HOURLY_PERMISSION = "HOURLY_PERMISSION"
    OTHER_LEAVE = "OTHER_LEAVE"


class TimeOffStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ============================================================================
# User Schemas
# ============================================================================

class UserBase(BaseModel):
    # Plain str on the response so synthetic @local.invalid placeholders
    # round-trip; inbound paths still use EmailStr.
    email: str
    username: str = Field(..., min_length=3, max_length=255)
    full_name: str
    title: Optional[str] = None
    department: Optional[str] = None
    timezone: Optional[str] = "UTC"
    role: UserRole = UserRole.EMPLOYEE
    is_active: bool = True
    manager_id: Optional[int] = None
    project_ids: List[int] = Field(default_factory=list)
    default_client_id: Optional[int] = None


class UserCreate(BaseModel):
    """Admin user creation. Only full_name + is_external are required."""
    full_name: str = Field(..., min_length=1)
    is_external: bool
    email: Optional[EmailStr] = None
    username: Optional[str] = Field(None, min_length=3, max_length=255)
    title: Optional[str] = None
    department: Optional[str] = None
    timezone: Optional[str] = "UTC"
    role: UserRole = UserRole.EMPLOYEE
    is_active: bool = True
    manager_id: Optional[int] = None
    project_ids: List[int] = Field(default_factory=list)
    default_client_id: Optional[int] = None
    password: Optional[str] = Field(None, min_length=8)
    can_review: bool = False
    # Only honored when PLATFORM_ADMIN creates a user in a specific tenant.
    tenant_id: Optional[int] = None


class UserSelfUpdate(BaseModel):
    full_name: Optional[str] = None
    title: Optional[str] = None
    timezone: Optional[str] = None
    username: Optional[str] = Field(None, min_length=3, max_length=255)
    # Email is self-editable only for platform admins (enforced in the route).
    email: Optional[EmailStr] = None


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = Field(None, min_length=3, max_length=255)
    full_name: Optional[str] = None
    title: Optional[str] = None
    department: Optional[str] = None
    timezone: Optional[str] = None
    role: Optional[UserRole] = None
    # CRUD layer dedupes and ensures the active role is included.
    roles: Optional[List[UserRole]] = None
    is_active: Optional[bool] = None
    can_review: Optional[bool] = None
    is_external: Optional[bool] = None
    manager_id: Optional[int] = None
    project_ids: Optional[List[int]] = None
    default_client_id: Optional[int] = None


class UserResponse(UserBase):
    id: int
    tenant_id: Optional[int] = None
    has_changed_password: bool
    email_verified: bool = False
    can_review: bool = False
    is_external: bool = False
    # Roles the user can act as; portal-picker shows when len(roles) > 1.
    roles: List[UserRole] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserCreateResponse(BaseModel):
    """Returned when an admin creates a new user."""
    user: UserResponse
    # Auto-generated password; admin hands this off when no verification email is sent.
    temporary_password: str
    verification_email_sent: bool = False


class UserSummaryResponse(BaseModel):
    id: int
    email: EmailStr
    username: str
    full_name: str
    title: Optional[str] = None
    department: Optional[str] = None
    role: UserRole
    is_active: bool
    has_changed_password: bool
    email_verified: bool = False
    can_review: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserProfileResponse(BaseModel):
    id: int
    email: EmailStr
    username: str
    full_name: str
    title: Optional[str] = None
    department: Optional[str] = None
    timezone: Optional[str] = None
    role: UserRole
    manager_id: Optional[int] = None
    manager_name: Optional[str] = None
    direct_reports: List[UserSummaryResponse] = Field(default_factory=list)
    supervisor_chain: List[UserSummaryResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class AdminPasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=8)


class MessageResponse(BaseModel):
    message: str


# ============================================================================
# Client Schemas
# ============================================================================

class ClientBase(BaseModel):
    name: str
    quickbooks_customer_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    quickbooks_customer_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None


class ClientResponse(ClientBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ============================================================================
# Project Schemas
# ============================================================================

class ProjectBase(BaseModel):
    name: str
    client_id: int
    billable_rate: Decimal
    quickbooks_project_id: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    estimated_hours: Optional[Decimal] = None
    budget_amount: Optional[Decimal] = None
    currency: Optional[str] = None
    is_active: bool = True


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    client_id: Optional[int] = None
    billable_rate: Optional[Decimal] = None
    quickbooks_project_id: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    estimated_hours: Optional[Decimal] = None
    budget_amount: Optional[Decimal] = None
    currency: Optional[str] = None
    is_active: Optional[bool] = None


class ProjectResponse(ProjectBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectWithClient(ProjectResponse):
    client: ClientResponse


class TaskBase(BaseModel):
    project_id: int
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    project_id: Optional[int] = None
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class TaskResponse(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskWithProject(TaskResponse):
    project: ProjectResponse


# ============================================================================
# TimeEntry Schemas
# ============================================================================

class TimeEntryBase(BaseModel):
    project_id: int
    task_id: Optional[int] = None
    entry_date: date
    hours: Decimal = Field(..., gt=0, le=24)
    description: str
    # Private free-text notes for the entry owner. Never surfaced in approval
    # queues, exports, or client-facing views.
    notes: Optional[str] = None
    is_billable: bool = True


class TimeEntryCreate(TimeEntryBase):
    pass


class TimeEntryUpdate(BaseModel):
    project_id: Optional[int] = None
    task_id: Optional[int] = None
    entry_date: Optional[date] = None
    hours: Optional[Decimal] = Field(None, gt=0, le=24)
    description: Optional[str] = None
    notes: Optional[str] = None
    is_billable: Optional[bool] = None
    edit_reason: Optional[str] = Field(None, max_length=2000)
    history_summary: Optional[str] = Field(None, max_length=2000)


class TimeEntryResponse(TimeEntryBase):
    id: int
    user_id: int
    status: TimeEntryStatus
    submitted_at: Optional[datetime] = None
    approved_by: Optional[int] = None
    approved_by_name: Optional[str] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    quickbooks_time_activity_id: Optional[str] = None
    last_edit_reason: Optional[str] = None
    last_history_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TimeEntryWithUser(TimeEntryResponse):
    user: UserSummaryResponse
    project: ProjectResponse
    task: Optional[TaskResponse] = None


class TimeEntrySubmitRequest(BaseModel):
    entry_ids: list[int]


class WeeklySubmissionStatusResponse(BaseModel):
    can_submit: bool
    reason: Optional[str] = None
    due_date: date


class TimeEntryApproveRequest(BaseModel):
    pass


class TimeEntryRejectRequest(BaseModel):
    rejection_reason: str = Field(..., min_length=1, max_length=1000)


class TimeEntryBatchApproveRequest(BaseModel):
    entry_ids: list[int]


class TimeEntryBatchRejectRequest(BaseModel):
    entry_ids: list[int]
    rejection_reason: str = Field(..., min_length=1, max_length=1000)


# ============================================================================
# TimeOff Schemas
# ============================================================================

class TimeOffRequestBase(BaseModel):
    request_date: date
    hours: Decimal = Field(..., gt=0, le=24)
    leave_type: str = Field(min_length=1, max_length=50)
    reason: str


class TimeOffRequestCreate(TimeOffRequestBase):
    pass


class TimeOffRequestUpdate(BaseModel):
    request_date: Optional[date] = None
    hours: Optional[Decimal] = Field(None, gt=0, le=24)
    leave_type: Optional[str] = Field(None, min_length=1, max_length=50)
    reason: Optional[str] = None


class LeaveTypeCreate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=100)
    color: Optional[str] = Field(default="#6b7280", max_length=20)


class LeaveTypeUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=100)
    color: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class LeaveTypeResponse(BaseModel):
    id: int
    tenant_id: int
    code: str
    label: str
    color: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TimeOffRequestResponse(TimeOffRequestBase):
    id: int
    user_id: int
    status: TimeOffStatus
    submitted_at: Optional[datetime] = None
    approved_by: Optional[int] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    external_reference: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TimeOffRequestWithUser(TimeOffRequestResponse):
    user: UserSummaryResponse


class TimeOffSubmitRequest(BaseModel):
    request_ids: list[int]


class TimeOffApproveRequest(BaseModel):
    pass


class TimeOffRejectRequest(BaseModel):
    rejection_reason: str = Field(..., min_length=1, max_length=1000)


# ============================================================================
# Dashboard Schemas
# ============================================================================

class DashboardSummaryResponse(BaseModel):
    hours_logged: Decimal
    approved_hours: Decimal
    pending_hours: Decimal
    pending_approvals: int
    team_members: int


class DashboardDayBreakdown(BaseModel):
    entry_date: date
    hours: Decimal
    formatted_date: str


class DashboardBarEntryDetail(BaseModel):
    entry_id: int
    project_id: int
    project_name: str
    client_name: str
    status: TimeEntryStatus
    description: str
    hours: Decimal
    entry_date: date


class DashboardDayProjectSegment(BaseModel):
    project_id: int
    project_name: str
    client_name: str
    hours: Decimal
    entries: list[DashboardBarEntryDetail]


class DashboardDayBreakdownDetailed(DashboardDayBreakdown):
    segments: list[DashboardDayProjectSegment] = []


class DashboardProjectBreakdown(BaseModel):
    project_id: int
    project_name: str
    client_name: str
    hours: Decimal
    percentage: float


class DashboardActivity(BaseModel):
    description: str
    project_name: str
    hours: Decimal


class DashboardAnalyticsResponse(BaseModel):
    total_hours: Decimal
    billable_hours: Decimal
    non_billable_hours: Decimal
    top_project_name: Optional[str]
    top_client_name: Optional[str]
    daily_breakdown: list[DashboardDayBreakdownDetailed]
    project_breakdown: list[DashboardProjectBreakdown]
    top_activities: list[DashboardActivity]


class DashboardRecentActivityItem(BaseModel):
    id: int
    activity_type: str
    entity_type: str
    entity_id: Optional[int] = None
    actor_name: Optional[str] = None
    summary: str
    route: str
    route_params: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None
    severity: str = "info"
    created_at: datetime

    model_config = {"from_attributes": True}


class TeamDailyOverviewResponse(BaseModel):
    date: date
    submission_deadline_at: datetime
    has_time_remaining_until_deadline: bool
    team_size: int
    submitted_yesterday_count: int
    submitted_yesterday: list[UserSummaryResponse]
    draft_yesterday_count: int
    draft_yesterday: list[UserSummaryResponse]
    missing_yesterday_count: int
    missing_yesterday: list[UserSummaryResponse]
    pending_approvals_count: int
    pending_time_entries_count: int
    pending_time_off_count: int
    total_hours_logged_yesterday: Decimal


# ============================================================================
# Manager Team Overview (week-to-date roster + capacity)
# ============================================================================

class ManagerTeamMemberStatus(BaseModel):
    """Per-employee week-to-date submission status for the roster grid.

    `working_days_in_week` is the count of weekdays (Mon-Fri) up to and
    including today. `submitted_days` is how many of those days the
    employee already has a SUBMITTED or APPROVED time entry on. The
    frontend renders the difference as `submitted/total` ("3/5 days").
    """

    user_id: int
    full_name: str
    working_days_in_week: int
    submitted_days: int
    is_on_pto_today: bool
    is_on_pto_this_week: bool
    upcoming_pto_starts_at: Optional[date] = None
    # Pattern badge: did this employee miss the deadline at least 2 of
    # the last 3 working days? Surfaced as a "repeatedly late" badge in
    # the roster so the manager can act on patterns, not one-offs.
    is_repeatedly_late: bool


class ManagerTeamCapacityEntry(BaseModel):
    """One row per active PTO occurrence within the lookahead window."""

    user_id: int
    full_name: str
    leave_type: str
    days_in_window: int


class ManagerTeamOverviewResponse(BaseModel):
    week_start: date
    week_end: date
    today: date
    team_size: int
    members: list[ManagerTeamMemberStatus]
    pending_approvals_count: int
    pending_time_off_count: int
    rejected_recent_count: int
    # Hours-old of the oldest pending approval. Surfaced as the "Avg
    # approval age" / "oldest" tile on the dashboard. None when the
    # queue is empty.
    pending_approvals_oldest_hours: Optional[int] = None
    pending_approvals_avg_hours: Optional[int] = None
    capacity_this_week: list[ManagerTeamCapacityEntry]
    capacity_next_week: list[ManagerTeamCapacityEntry]


class ManagerProjectHealthRow(BaseModel):
    """Per-project row for the manager dashboard project-health table.

    Only includes projects that have time entries from the manager's
    scoped team within the last lookback window. We don't list every
    project in the tenant; that would be noise.
    """

    project_id: int
    project_name: str
    client_name: str
    # Days remaining until end_date. Negative when overdue. None when
    # the project has no end_date set ("Open").
    days_until_end: Optional[int]
    hours_this_week: Decimal
    # Budget consumed as percentage. None when no estimated_hours set.
    budget_pct: Optional[int]
    # Hours remaining against the budget. Negative when over.
    budget_hours_remaining: Optional[Decimal]
    # 'good' | 'at-risk' | 'needs-attention' | 'not-set'
    health: str


class ManagerProjectHealthResponse(BaseModel):
    rows: list[ManagerProjectHealthRow]


# ============================================================================
# Email Verification Schemas
# ============================================================================

class VerifyEmailRequest(BaseModel):
    token: str


class VerifyEmailResponse(BaseModel):
    message: str
    email: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


# ============================================================================
# Auth Schemas
# ============================================================================

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class PasswordChangeResponse(BaseModel):
    success: bool = True
    message: str = "Password changed successfully"


class RefreshRequest(BaseModel):
    refresh_token: str


class RoleSwitchRequest(BaseModel):
    """Body for POST /auth/switch-role. The requested role must be in
    current_user.roles; the endpoint flips the active role and mints
    a fresh access + refresh pair."""
    role: UserRole


class RoleHandoffIssueResponse(BaseModel):
    """Response for POST /auth/role-handoff. Carries the short-lived
    JWT that the new tab passes to /auth/role-handoff/exchange to
    obtain its own session for the same user with the requested role
    active."""
    handoff_token: str
    target_role: UserRole


class RoleHandoffExchangeRequest(BaseModel):
    handoff_token: str


# ============================================================================
# Tenant Schemas
# ============================================================================

class TenantStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    suspended = "suspended"


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    slug: Optional[str] = Field(None, min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    status: Optional[TenantStatus] = None
    ingestion_enabled: Optional[bool] = None
    max_mailboxes: Optional[int] = Field(None, ge=0)
    # IANA timezone name (e.g. "America/New_York"). ``None`` means "fall back
    # to UTC." Empty string is treated as clearing the value — the endpoint
    # already passes through via ``model_dump(exclude_unset=True)``.
    timezone: Optional[str] = Field(None, max_length=64)


class TenantResponse(BaseModel):
    id: int
    name: str
    slug: str
    status: TenantStatus
    ingestion_enabled: bool = False
    max_mailboxes: Optional[int] = None
    timezone: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class DepartmentResponse(BaseModel):
    id: int
    tenant_id: int
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NotificationItem(BaseModel):
    id: str
    title: str
    message: str
    route: str
    severity: str = "info"
    count: int = 1
    created_at: Optional[datetime] = None
    is_read: bool = False


class NotificationRouteCounts(BaseModel):
    my_time: int = 0
    time_off: int = 0
    approvals: int = 0
    admin: int = 0
    dashboard: int = 0


class NotificationSummaryResponse(BaseModel):
    total_count: int
    route_counts: NotificationRouteCounts
    items: list[NotificationItem]


class NotificationReadRequest(BaseModel):
    notification_id: str


class NotificationActionResponse(BaseModel):
    success: bool = True
