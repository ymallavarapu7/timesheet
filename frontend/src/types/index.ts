// User types
export type UserRole = 'EMPLOYEE' | 'MANAGER' | 'SENIOR_MANAGER' | 'CEO' | 'ADMIN' | 'PLATFORM_ADMIN';

export interface User {
  id: number;
  email: string;
  username: string;
  full_name: string;
  title?: string | null;
  department?: string | null;
  timezone?: string | null;
  role: UserRole;
  is_active: boolean;
  has_changed_password: boolean;
  email_verified: boolean;
  can_review?: boolean;
  is_external?: boolean;
  tenant_id: number | null;
  manager_id?: number | null;
  project_ids?: number[];
  timesheet_locked?: boolean;
  timesheet_locked_reason?: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserCreateResponse {
  user: User;
  temporary_password: string;
}

export interface UserProfile {
  id: number;
  email: string;
  username: string;
  full_name: string;
  title?: string | null;
  department?: string | null;
  timezone?: string | null;
  role: UserRole;
  has_changed_password: boolean;
  manager_id?: number | null;
  manager_name?: string | null;
  direct_reports: User[];
  supervisor_chain: User[];
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface MessageResponse {
  message: string;
}

// Client types
export interface Client {
  id: number;
  name: string;
  quickbooks_customer_id: string | null;
  created_at: string;
  updated_at: string;
}

// Project types
export interface Project {
  id: number;
  name: string;
  client_id: number;
  billable_rate: string | number;
  quickbooks_project_id: string | null;
  code?: string | null;
  description?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  estimated_hours?: string | number | null;
  budget_amount?: string | number | null;
  currency?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  client?: Client;
}

export interface Task {
  id: number;
  project_id: number;
  name: string;
  code?: string | null;
  description?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  project?: Project;
}

// TimeEntry types
export type TimeEntryStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'REJECTED';
export type TimeOffType = 'SICK_DAY' | 'PTO' | 'HALF_DAY' | 'HOURLY_PERMISSION' | 'OTHER_LEAVE';
export type TimeOffStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'REJECTED';

export interface TimeEntry {
  id: number;
  user_id: number;
  project_id: number;
  task_id?: number | null;
  entry_date: string;
  hours: string | number;
  description: string;
  is_billable: boolean;
  status: TimeEntryStatus;
  submitted_at: string | null;
  approved_by: number | null;
  approved_at: string | null;
  rejection_reason: string | null;
  quickbooks_time_activity_id: string | null;
  created_at: string;
  updated_at: string;
  user?: User;
  project?: Project;
  task?: Task;
}

export interface TimeOffRequest {
  id: number;
  user_id: number;
  request_date: string;
  hours: string | number;
  leave_type: TimeOffType;
  reason: string;
  status: TimeOffStatus;
  submitted_at: string | null;
  approved_by: number | null;
  approved_at: string | null;
  rejection_reason: string | null;
  external_reference: string | null;
  created_at: string;
  updated_at: string;
  user?: User;
}

export interface DashboardSummary {
  hours_logged: string | number;
  approved_hours: string | number;
  pending_hours: string | number;
  pending_approvals: number;
  team_members: number;
}

export interface TeamDailyOverview {
  date: string;
  submission_deadline_at: string;
  has_time_remaining_until_deadline: boolean;
  team_size: number;
  submitted_yesterday_count: number;
  submitted_yesterday: User[];
  draft_yesterday_count: number;
  draft_yesterday: User[];
  missing_yesterday_count: number;
  missing_yesterday: User[];
  pending_approvals_count: number;
  pending_time_entries_count: number;
  pending_time_off_count: number;
  total_hours_logged_yesterday: string | number;
}

export interface DashboardDayBreakdown {
  entry_date: string;
  hours: string | number;
  formatted_date: string;
  segments: DashboardDayProjectSegment[];
}

export interface DashboardBarEntryDetail {
  entry_id: number;
  project_id: number;
  project_name: string;
  client_name: string;
  status: TimeEntryStatus;
  description: string;
  hours: string | number;
  entry_date: string;
}

export interface DashboardDayProjectSegment {
  project_id: number;
  project_name: string;
  client_name: string;
  hours: string | number;
  entries: DashboardBarEntryDetail[];
}

export interface DashboardProjectBreakdown {
  project_id: number;
  project_name: string;
  client_name: string;
  hours: string | number;
  percentage: number;
}

export interface DashboardActivity {
  description: string;
  project_name: string;
  hours: string | number;
}

export interface DashboardRecentActivityItem {
  id: number;
  activity_type: string;
  entity_type: string;
  entity_id: number | null;
  actor_name: string | null;
  summary: string;
  route: string;
  route_params: Record<string, string | number | boolean | null> | null;
  metadata: Record<string, string | number | boolean | null | string[] | number[]> | null;
  severity: 'info' | 'warning' | 'success' | 'error' | string;
  created_at: string;
}

export interface DashboardAnalytics {
  total_hours: string | number;
  billable_hours: string | number;
  non_billable_hours: string | number;
  top_project_name: string | null;
  top_client_name: string | null;
  daily_breakdown: DashboardDayBreakdown[];
  project_breakdown: DashboardProjectBreakdown[];
  top_activities: DashboardActivity[];
}

export interface NotificationItem {
  id: string;
  title: string;
  message: string;
  route: string;
  severity: 'info' | 'warning' | 'success' | 'error' | string;
  count: number;
  created_at: string | null;
  is_read: boolean;
}

export interface NotificationRouteCounts {
  my_time: number;
  time_off: number;
  approvals: number;
  admin: number;
  dashboard: number;
}

export interface NotificationSummary {
  total_count: number;
  route_counts: NotificationRouteCounts;
  items: NotificationItem[];
}

export interface NotificationActionResponse {
  success: boolean;
}

export interface WeeklySubmissionStatus {
  can_submit: boolean;
  reason: string | null;
  due_date: string;
}

// Service Token types
export interface ServiceToken {
  id: number;
  name: string;
  tenant_id: number;
  issuer: string;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
}

export interface ServiceTokenCreated extends ServiceToken {
  token: string;
}

export interface ServiceTokenCreate {
  name: string;
  issuer: string;
}

// Tenant types
export type TenantStatus = 'active' | 'inactive' | 'suspended';

export interface Tenant {
  id: number;
  name: string;
  slug: string;
  status: TenantStatus;
  ingestion_enabled: boolean;
  created_at: string;
  updated_at: string;
}

// Auth types
export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token?: string;
  token_type: string;
  user: User;
}

export interface AuthState {
  user: User | null;
  tenant: Tenant | null;
  accessToken: string | null;
  isLoading: boolean;
  error: string | null;
}

export type MailboxProtocol = 'imap' | 'pop3' | 'graph';
export type MailboxAuthType = 'basic' | 'oauth2';
export type OAuthProvider = 'google' | 'microsoft';
export type MappingMatchType = 'email' | 'domain';
export type IngestionStatus = 'pending' | 'under_review' | 'approved' | 'rejected' | 'on_hold';

export interface Mailbox {
  id: number;
  tenant_id: number;
  label: string;
  protocol: MailboxProtocol | string;
  auth_type: MailboxAuthType | string;
  host: string | null;
  port: number | null;
  use_ssl: boolean;
  username: string | null;
  has_password: boolean;
  oauth_provider: OAuthProvider | string | null;
  oauth_email: string | null;
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_username: string | null;
  linked_client_id: number | null;
  is_active: boolean;
  last_fetched_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MailboxPayload {
  label: string;
  protocol: MailboxProtocol | string;
  auth_type: MailboxAuthType | string;
  host?: string | null;
  port?: number | null;
  use_ssl?: boolean;
  username?: string | null;
  password?: string | null;
  oauth_provider?: OAuthProvider | string | null;
  smtp_host?: string | null;
  smtp_port?: number | null;
  smtp_username?: string | null;
  smtp_password?: string | null;
  linked_client_id?: number | null;
  is_active?: boolean;
}

export interface Mapping {
  id: number;
  tenant_id: number;
  match_type: MappingMatchType | string;
  match_value: string;
  client_id: number;
  employee_id: number | null;
  created_at: string;
}

export interface MappingPayload {
  match_type?: MappingMatchType | string;
  match_value?: string;
  client_id?: number;
  employee_id?: number | null;
}

export interface FetchJobResponse {
  job_id: string;
  status: string;
  message?: string | null;
}

export interface FetchJobStatus {
  status: string;
  job_id: string;
  progress?: number | null;
  message?: string | null;
  tenant_id?: number | null;
  mode?: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface FetchMessageDiagnostic {
  email_id?: number | null;
  message_id?: string | null;
  subject?: string | null;
  sender_email?: string | null;
  skipped?: boolean;
  skip_reason?: string | null;
  skip_detail?: string | null;
  timesheets_created?: number;
  errors?: string[];
}

export interface ReprocessSkippedResult {
  job_id: string;
  status: string;
  deleted_emails: number;
  deleted_attachments: number;
  deleted_files: number;
  file_delete_errors: number;
}

export interface SkippedEmail {
  id: number;
  subject: string | null;
  sender_email: string;
  sender_name: string | null;
  received_at: string | null;
  mailbox_label: string | null;
  has_attachments: boolean;
  timesheet_attachment_count: number;
  classification_intent: string | null;
  skip_reason: string | null;
  skip_detail: string | null;
  reprocessable_attachments: Array<{
    id: number;
    filename: string;
    mime_type: string | null;
    extraction_status: string;
  }>;
}

export interface SkippedEmailOverview {
  count: number;
  emails: SkippedEmail[];
}

export interface SpreadsheetPreviewBlock {
  rows: string[][];
}

export interface SpreadsheetPreviewSheet {
  name: string;
  rows: string[][];
  blocks?: SpreadsheetPreviewBlock[];
}

export interface SpreadsheetPreview {
  sheets: SpreadsheetPreviewSheet[];
}

export interface EmailAttachmentSummary {
  id: number;
  filename: string;
  mime_type: string | null;
  size_bytes: number | null;
  is_timesheet: boolean;
  extraction_method: string | null;
  extraction_status: string;
  extraction_error?: string | null;
  raw_extracted_text?: string | null;
  spreadsheet_preview?: SpreadsheetPreview | null;
  rendered_html?: string | null;
}

export interface IngestionEmailContext {
  id: number;
  subject: string | null;
  sender_email: string;
  sender_name: string | null;
  recipients: unknown;
  body_text: string | null;
  body_html: string | null;
  received_at: string | null;
  attachments: EmailAttachmentSummary[];
}

export interface StoredEmailDetail {
  id: number;
  subject: string | null;
  sender_email: string;
  sender_name: string | null;
  recipients: unknown;
  body_text: string | null;
  body_html: string | null;
  received_at: string | null;
  mailbox_label: string | null;
  classification_intent: string | null;
  skip_reason: string | null;
  skip_detail: string | null;
  llm_classification: Record<string, unknown> | null;
  attachments: EmailAttachmentSummary[];
}

export interface IngestionLineItem {
  id: number;
  work_date: string;
  hours: string | number;
  description: string | null;
  project_code: string | null;
  project_id: number | null;
  is_corrected: boolean;
  original_value: Record<string, unknown> | null;
  is_rejected: boolean;
  rejection_reason: string | null;
}

export interface IngestionAuditLog {
  id: number;
  action: string;
  actor_type: string;
  user_id: number | null;
  previous_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  comment: string | null;
  created_at: string;
}

export interface IngestionTimesheetSummary {
  id: number;
  tenant_id: number;
  email_id: number;
  attachment_id: number | null;
  subject: string | null;
  sender_email: string | null;
  sender_name: string | null;
  employee_id: number | null;
  employee_name: string | null;
  extracted_employee_name: string | null;
  extracted_supervisor_name: string | null;
  client_id: number | null;
  client_name: string | null;
  period_start: string | null;
  period_end: string | null;
  total_hours: string | number | null;
  status: IngestionStatus | string;
  push_status: string | null;
  time_entries_created: boolean;
  is_likely_resubmission?: boolean;
  llm_anomalies: Array<Record<string, unknown>> | null;
  received_at: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export interface IngestionTimesheetDetail {
  id: number;
  tenant_id: number;
  attachment_id: number | null;
  status: IngestionStatus | string;
  employee_id: number | null;
  employee_name: string | null;
  client_id: number | null;
  client_name: string | null;
  reviewer_id: number | null;
  period_start: string | null;
  period_end: string | null;
  total_hours: string | number | null;
  extracted_data: Record<string, unknown> | null;
  corrected_data: Record<string, unknown> | null;
  llm_anomalies: Array<Record<string, unknown>> | null;
  llm_match_suggestions: Record<string, unknown> | null;
  llm_summary: string | null;
  rejection_reason: string | null;
  internal_notes: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
  time_entries_created: boolean;
  extracted_employee_name: string | null;
  extracted_supervisor_name: string | null;
  email: IngestionEmailContext | null;
  line_items: IngestionLineItem[];
  audit_log: IngestionAuditLog[];
}

export interface IngestionDataUpdate {
  employee_id?: number | null;
  client_id?: number | null;
  period_start?: string | null;
  period_end?: string | null;
  total_hours?: string | number | null;
  internal_notes?: string | null;
}

export interface IngestionLineItemPayload {
  work_date?: string;
  hours?: string | number;
  description?: string | null;
  project_code?: string | null;
  project_id?: number | null;
}

export interface IngestionApprovalResult {
  ingestion_timesheet_id: number;
  time_entries_created: number;
  employee_id: number;
  project_ids: number[];
  status: string;
  overlapping_entries_count: number;
  overlapping_dates: string[];
}

export interface ReprocessStoredEmailResult {
  job_id: string;
  status: string;
  mode: string;
  email_id: number;
}

export interface MappingReapplyResult {
  checked: number;
  updated: number;
}
