import { apiClient } from './client';

export type HistoryGroupEntry = {
  id: number;
  entry_date: string;
  hours: number;
  description: string | null;
  status: string;
  rejection_reason: string | null;
  project_name: string | null;
  task_name: string | null;
};

export type HistoryGroup = {
  employee_id: number;
  employee_name: string;
  week_start: string;
  week_end: string;
  total_hours: number;
  entry_count: number;
  approved_count: number;
  rejected_count: number;
  status: 'approved' | 'rejected' | 'mixed';
  entries: HistoryGroupEntry[];
};

import {
  ChangePasswordRequest,
  UserCreateResponse,
  DashboardAnalytics,
  DashboardRecentActivityItem,
  DashboardSummary,
  FetchJobResponse,
  FetchJobStatus,
  IngestionApprovalResult,
  IngestionDataUpdate,
  IngestionLineItem,
  IngestionLineItemPayload,
  IngestionTimesheetDetail,
  IngestionTimesheetSummary,
  LoginRequest,
  MappingReapplyResult,
  Mailbox,
  MailboxPayload,
  Mapping,
  MappingPayload,
  MessageResponse,
  NotificationActionResponse,
  NotificationSummary,
  ReprocessSkippedResult,
  ReprocessStoredEmailResult,
  ServiceToken,
  ServiceTokenCreate,
  ServiceTokenCreated,
  StoredEmailDetail,
  Task,
  TeamDailyOverview,
  Tenant,
  TenantStatus,
  TimeEntry,
  TimeOffRequest,
  TokenResponse,
  User,
  UserProfile,
  SkippedEmailOverview,
  WeeklySubmissionStatus,
} from '@/types';

// Auth endpoints
export const authAPI = {
  login: (data: LoginRequest) =>
    apiClient.post<TokenResponse>('/auth/login', data),
  
  me: () =>
    apiClient.get<User>('/auth/me'),

  changePassword: (data: ChangePasswordRequest) =>
    apiClient.post<MessageResponse>('/auth/change-password', data),

  refresh: (refreshToken: string) =>
    apiClient.post<TokenResponse>('/auth/refresh', { refresh_token: refreshToken }),

  logout: (refreshToken: string) =>
    apiClient.post('/auth/logout', { refresh_token: refreshToken }),

  verifyEmail: (token: string) =>
    apiClient.post<MessageResponse & { email: string }>('/auth/verify-email', { token }),

  resendVerification: (email: string) =>
    apiClient.post<MessageResponse>('/auth/resend-verification', { email }),
};

// Users endpoints
export const usersAPI = {
  list: () =>
    apiClient.get<User[]>('/users'),
  
  get: (id: number) =>
    apiClient.get<User>(`/users/${id}`),
  
  create: (data: Partial<User> & { password?: string }) =>
    apiClient.post<UserCreateResponse>('/users', data),
  
  update: (id: number, data: Partial<User>) =>
    apiClient.put<User>(`/users/${id}`, data),

  meProfile: () =>
    apiClient.get<UserProfile>('/users/me/profile'),

  updateMyProfile: (data: { full_name?: string; title?: string; department?: string; timezone?: string }) =>
    apiClient.patch<User>('/users/me/profile', data),

  changePassword: (data: ChangePasswordRequest) =>
    apiClient.post<MessageResponse>('/auth/change-password', data),

  changePasswordAfterVerification: async (tempPassword: string, newPassword: string, email: string) => {
    // Log in with the temp password to get a short-lived token, then change password
    const loginRes = await apiClient.post<TokenResponse>('/auth/login', { email, password: tempPassword });
    const token = loginRes.data.access_token;
    return apiClient.post<MessageResponse>(
      '/users/me/password',
      { current_password: tempPassword, new_password: newPassword },
      { headers: { Authorization: `Bearer ${token}` } },
    );
  },

  delete: (id: number) =>
    apiClient.delete(`/users/${id}`),
  bulkDelete: (userIds: number[]) =>
    apiClient.post<{ deleted: number }>('/users/bulk-delete', { user_ids: userIds }),
  resetPassword: (id: number, newPassword: string) =>
    apiClient.post<{ message: string }>(`/users/${id}/reset-password`, { new_password: newPassword }),
};

// Clients endpoints
export const clientsAPI = {
  list: () =>
    apiClient.get('/clients'),
  
  get: (id: number) =>
    apiClient.get(`/clients/${id}`),
  
  create: (data: { name: string; quickbooks_customer_id?: string }) =>
    apiClient.post('/clients', data),
  
  update: (id: number, data: Partial<{ name: string; quickbooks_customer_id: string }>) =>
    apiClient.put(`/clients/${id}`, data),
  
  delete: (id: number) =>
    apiClient.delete(`/clients/${id}`),
};

// Projects endpoints
export const projectsAPI = {
  list: (params?: { client_id?: number; active_only?: boolean; skip?: number; limit?: number }) =>
    apiClient.get('/projects', { params }),
  
  get: (id: number) =>
    apiClient.get(`/projects/${id}`),
  
  create: (data: {
    name: string;
    client_id: number;
    billable_rate: number;
    quickbooks_project_id?: string;
    code?: string;
    description?: string;
    start_date?: string;
    end_date?: string;
    estimated_hours?: number;
    budget_amount?: number;
    currency?: string;
    is_active?: boolean;
  }) =>
    apiClient.post('/projects', data),
  
  update: (id: number, data: Partial<Record<string, unknown>>) =>
    apiClient.put(`/projects/${id}`, data),
  
  delete: (id: number) =>
    apiClient.delete(`/projects/${id}`),
};

export const tasksAPI = {
  list: (params?: { project_id?: number; active_only?: boolean; skip?: number; limit?: number }) =>
    apiClient.get<Task[]>('/tasks', { params }),

  get: (id: number) =>
    apiClient.get<Task>(`/tasks/${id}`),

  create: (data: {
    project_id: number;
    name: string;
    code?: string;
    description?: string;
    is_active?: boolean;
  }) =>
    apiClient.post<Task>('/tasks', data),

  update: (id: number, data: Partial<{ project_id: number; name: string; code: string; description: string; is_active: boolean }>) =>
    apiClient.put<Task>(`/tasks/${id}`, data),

  delete: (id: number) =>
    apiClient.delete(`/tasks/${id}`),
};

// TimeEntries endpoints
export const timeentriesAPI = {
  list: (params?: {
    start_date?: string;
    end_date?: string;
    status?: string;
    search?: string;
    sort_by?: 'entry_date' | 'created_at' | 'hours' | 'status';
    sort_order?: 'asc' | 'desc';
    skip?: number;
    limit?: number;
  }) =>
    apiClient.get('/timesheets/my', { params }),
  
  get: (id: number) =>
    apiClient.get(`/timesheets/${id}`),
  
  create: (data: {
    project_id: number;
    task_id?: number | null;
    entry_date: string;
    hours: number;
    description: string;
    is_billable?: boolean;
  }) =>
    apiClient.post('/timesheets', data),
  
  update: (id: number, data: Partial<Record<string, unknown>>) =>
    apiClient.put(`/timesheets/${id}`, data),
  
  delete: (id: number) =>
    apiClient.delete(`/timesheets/${id}`),
  
  submit: (entry_ids: number[]) =>
    apiClient.post('/timesheets/submit', { entry_ids }),

  weeklySubmitStatus: () =>
    apiClient.get<WeeklySubmissionStatus>('/timesheets/weekly-submit-status'),

  parseNatural: (text: string) =>
    apiClient.post<{
      entries: Array<{
        project_id: number | null;
        project_name: string;
        task_id: number | null;
        task_name: string;
        client_name: string;
        client_id: number | null;
        entry_date: string;
        hours: number | null;
        description: string;
        is_billable: boolean;
        error: string | null;
        alternatives: Array<{
          project_id: number;
          project_name: string;
          task_id: number;
          task_name: string;
        }>;
      }>;
      raw_input?: string;
      error?: string;
    }>('/timesheets/parse-natural', { text }),

  listAll: (params?: {
    user_id?: number;
    start_date?: string;
    end_date?: string;
    status?: string;
    sort_by?: 'entry_date' | 'created_at' | 'hours' | 'status';
    sort_order?: 'asc' | 'desc';
    skip?: number;
    limit?: number;
  }) =>
    apiClient.get<TimeEntry[]>('/timesheets/all', { params }),
};

// Approvals endpoints
export const approvalsAPI = {
  pending: (params?: {
    search?: string;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
    skip?: number;
    limit?: number;
  }) =>
    apiClient.get('/approvals/pending', { params }),

  history: (params?: {
    search?: string;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
    include_older?: boolean;
    skip?: number;
    limit?: number;
  }) =>
    apiClient.get('/approvals/history', { params }),
  
  approve: (id: number) =>
    apiClient.post(`/approvals/${id}/approve`, {}),

  batchApprove: (entry_ids: number[]) =>
    apiClient.post('/approvals/batch-approve', { entry_ids }),
  
  reject: (id: number, rejection_reason: string) =>
    apiClient.post(`/approvals/${id}/reject`, { rejection_reason }),

  batchReject: (entry_ids: number[], rejection_reason: string) =>
    apiClient.post('/approvals/batch-reject', { entry_ids, rejection_reason }),

  revertRejection: (id: number) =>
    apiClient.post<{ status: string }>(`/approvals/${id}/revert-rejection`, {}),

  historyGrouped: (params?: { days_back?: number; status_filter?: string }) =>
    apiClient.get<HistoryGroup[]>('/approvals/history-grouped', { params }),
};

export const timeOffAPI = {
  list: (params?: {
    start_date?: string;
    end_date?: string;
    status?: string;
    leave_type?: string;
    search?: string;
    sort_by?: 'request_date' | 'created_at' | 'hours' | 'status';
    sort_order?: 'asc' | 'desc';
    skip?: number;
    limit?: number;
  }) => apiClient.get<TimeOffRequest[]>('/time-off/my', { params }),

  get: (id: number) => apiClient.get<TimeOffRequest>(`/time-off/${id}`),

  create: (data: {
    request_date: string;
    hours: number;
    leave_type: string;
    reason: string;
  }) => apiClient.post<TimeOffRequest>('/time-off', data),

  update: (id: number, data: Partial<{ request_date: string; hours: number; leave_type: string; reason: string }>) =>
    apiClient.put<TimeOffRequest>(`/time-off/${id}`, data),

  delete: (id: number) => apiClient.delete(`/time-off/${id}`),

  submit: (request_ids: number[]) => apiClient.post<TimeOffRequest[]>('/time-off/submit', { request_ids }),
};

export const timeOffApprovalsAPI = {
  pending: (params?: {
    search?: string;
    sort_by?: 'request_date' | 'submitted_at' | 'hours' | 'employee';
    sort_order?: 'asc' | 'desc';
    skip?: number;
    limit?: number;
  }) => apiClient.get<TimeOffRequest[]>('/time-off-approvals/pending', { params }),

  history: (params?: {
    search?: string;
    sort_by?: 'approved_at' | 'request_date' | 'hours' | 'employee' | 'status';
    sort_order?: 'asc' | 'desc';
    include_older?: boolean;
    skip?: number;
    limit?: number;
  }) => apiClient.get<TimeOffRequest[]>('/time-off-approvals/history', { params }),

  approve: (id: number) => apiClient.post<TimeOffRequest>(`/time-off-approvals/${id}/approve`, {}),

  reject: (id: number, rejection_reason: string) =>
    apiClient.post<TimeOffRequest>(`/time-off-approvals/${id}/reject`, { rejection_reason }),
};

export const dashboardAPI = {
  summary: () => apiClient.get<DashboardSummary>('/dashboard/summary'),
  team: () => apiClient.get<User[]>('/dashboard/team'),
  teamDailyOverview: () => apiClient.get<TeamDailyOverview>('/dashboard/team-daily-overview'),
  analytics: (params: {
    start_date: string;
    end_date: string;
    project_id?: number;
    user_id?: number;
  }) => apiClient.get<DashboardAnalytics>('/dashboard/analytics', { params }),
  recentActivity: (params?: { limit?: number }) =>
    apiClient.get<DashboardRecentActivityItem[]>('/dashboard/recent-activity', { params }),
  auditTrail: (params?: { limit?: number; offset?: number; activity_type?: string; search?: string }) =>
    apiClient.get<DashboardRecentActivityItem[]>('/dashboard/audit-trail', { params }),
};

export const notificationsAPI = {
  summary: () => apiClient.get<NotificationSummary>('/notifications/summary'),
  markRead: (notification_id: string) =>
    apiClient.post<NotificationActionResponse>('/notifications/read', { notification_id }),
  markAllRead: () =>
    apiClient.post<NotificationActionResponse>('/notifications/read-all', {}),
  deleteOne: (notification_id: string) =>
    apiClient.post<NotificationActionResponse>('/notifications/delete', { notification_id }),
  deleteAll: () =>
    apiClient.post<NotificationActionResponse>('/notifications/delete-all', {}),
};

export const tenantsAPI = {
  mine: () => apiClient.get<Tenant>('/tenants/mine'),
  list: () => apiClient.get<Tenant[]>('/tenants'),
  get: (id: number) => apiClient.get<Tenant>(`/tenants/${id}`),
  create: (data: { name: string; slug: string }) => apiClient.post<Tenant>('/tenants', data),
  update: (id: number, data: { name?: string; slug?: string; status?: TenantStatus; ingestion_enabled?: boolean }) =>
    apiClient.patch<Tenant>(`/tenants/${id}`, data),
  provisionSystemUser: (id: number) =>
    apiClient.post<{ provisioned: boolean; user_id: number; email: string }>(`/tenants/${id}/provision-system-user`),
  getServiceTokens: (tenantId: number) =>
    apiClient.get<ServiceToken[]>(`/tenants/${tenantId}/service-tokens`),
  createServiceToken: (tenantId: number, data: ServiceTokenCreate) =>
    apiClient.post<ServiceTokenCreated>(`/tenants/${tenantId}/service-tokens`, data),
  revokeServiceToken: (tenantId: number, tokenId: number) =>
    apiClient.delete(`/tenants/${tenantId}/service-tokens/${tokenId}`),
};

export const tenantSettingsAPI = {
  get: () => apiClient.get<Record<string, string | null>>('/users/tenant-settings'),
  update: (data: Record<string, string | null>) =>
    apiClient.patch<Record<string, string | null>>('/users/tenant-settings', data),
  unlockUser: (userId: number) =>
    apiClient.post<{ success: boolean; user_id: number }>(`/users/users/${userId}/unlock-timesheet`, {}),
};

export const mailboxesAPI = {
  list: () => apiClient.get<Mailbox[]>('/api/mailboxes'),
  get: (id: number) => apiClient.get<Mailbox>(`/api/mailboxes/${id}`),
  create: (data: MailboxPayload) => apiClient.post<Mailbox>('/api/mailboxes', data),
  update: (id: number, data: Partial<MailboxPayload>) => apiClient.patch<Mailbox>(`/api/mailboxes/${id}`, data),
  delete: (id: number) => apiClient.delete(`/api/mailboxes/${id}`),
  test: (id: number) => apiClient.post<{ success: boolean; error: string | null; latency_ms: number; message_count: number }>(`/api/mailboxes/${id}/test`, {}),
  resetCursor: (id: number) => apiClient.post(`/api/mailboxes/${id}/reset-cursor`, {}),
  oauthConnect: (provider: 'google' | 'microsoft') => apiClient.get<{ auth_url: string }>(`/api/mailboxes/oauth/connect/${provider}`),
};

export const mappingsAPI = {
  list: () => apiClient.get<Mapping[]>('/api/mappings'),
  create: (data: Required<Pick<MappingPayload, 'match_type' | 'match_value' | 'client_id'>> & { employee_id?: number | null }) =>
    apiClient.post<Mapping>('/api/mappings', data),
  update: (id: number, data: MappingPayload) => apiClient.patch<Mapping>(`/api/mappings/${id}`, data),
  delete: (id: number) => apiClient.delete(`/api/mappings/${id}`),
  bulkDelete: (mappingIds: number[]) =>
    apiClient.post<{ deleted: number }>('/api/mappings/bulk-delete', { mapping_ids: mappingIds }),
};

export const ingestionAPI = {
  triggerFetch: () => apiClient.post<FetchJobResponse>('/api/ingestion/fetch-emails', {}),
  getFetchStatus: (jobId: string) => apiClient.get<FetchJobStatus>(`/api/ingestion/fetch-emails/status/${jobId}`),
  getSkippedEmails: (params?: { limit?: number }) => apiClient.get<SkippedEmailOverview>('/api/ingestion/skipped-emails', { params }),
  reprocessSkipped: () => apiClient.post<ReprocessSkippedResult>('/api/ingestion/fetch-emails/reprocess-skipped', {}),
  reprocessEmail: (emailId: number, attachmentIds?: number[]) =>
    apiClient.post<ReprocessStoredEmailResult>('/api/ingestion/fetch-emails/reprocess', { email_id: emailId, attachment_ids: attachmentIds }),
  getEmail: (emailId: number) => apiClient.get<StoredEmailDetail>(`/api/ingestion/emails/${emailId}`),
  deleteEmail: (emailId: number, refetch: boolean = false) =>
    apiClient.delete(`/api/ingestion/emails/${emailId}`, { params: refetch ? { refetch: true } : undefined }),
  bulkDeleteEmails: (emailIds: number[]) =>
    apiClient.post<{ deleted: number }>('/api/ingestion/emails/bulk-delete', { email_ids: emailIds }),
  bulkReprocess: (emailIds: number[]) =>
    apiClient.post<{ queued: number; message: string }>('/api/ingestion/fetch-emails/bulk-reprocess', { email_ids: emailIds }),
  reapplyMappings: () => apiClient.post<MappingReapplyResult>('/api/ingestion/timesheets/reapply-mappings', {}),
  getAttachmentFile: async (attachmentId: number) => {
    const response = await apiClient.get<Blob>(`/api/ingestion/attachments/${attachmentId}/file`, {
      responseType: 'blob',
      headers: { Accept: '*/*' },
    });
    return URL.createObjectURL(response.data);
  },
  listTimesheets: (params?: { status_filter?: string; client_id?: number; employee_id?: number; email_id?: number; search?: string; limit?: number; offset?: number }) =>
    apiClient.get<IngestionTimesheetSummary[]>('/api/ingestion/timesheets', { params }),
  getTimesheet: (id: number) => apiClient.get<IngestionTimesheetDetail>(`/api/ingestion/timesheets/${id}`),
  updateTimesheetData: (id: number, data: IngestionDataUpdate) => apiClient.patch<{ status: string }>(`/api/ingestion/timesheets/${id}/data`, data),
  addLineItem: (id: number, data: Required<Pick<IngestionLineItemPayload, 'work_date' | 'hours'>> & IngestionLineItemPayload) =>
    apiClient.post<IngestionLineItem>(`/api/ingestion/timesheets/${id}/line-items`, data),
  updateLineItem: (timesheetId: number, itemId: number, data: IngestionLineItemPayload) =>
    apiClient.patch<IngestionLineItem>(`/api/ingestion/timesheets/${timesheetId}/line-items/${itemId}`, data),
  deleteLineItem: (timesheetId: number, itemId: number) =>
    apiClient.delete(`/api/ingestion/timesheets/${timesheetId}/line-items/${itemId}`),
  approveTimesheet: (id: number, comment?: string) =>
    apiClient.post<IngestionApprovalResult>(`/api/ingestion/timesheets/${id}/approve`, { comment }),
  rejectTimesheet: (id: number, reason: string, comment?: string) =>
    apiClient.post<{ status: string; reason: string }>(`/api/ingestion/timesheets/${id}/reject`, { reason, comment }),
  holdTimesheet: (id: number, comment?: string) =>
    apiClient.post<{ status: string }>(`/api/ingestion/timesheets/${id}/hold`, { comment }),
  rejectLineItem: (timesheetId: number, itemId: number, reason: string) =>
    apiClient.post<{ status: string; line_item_id: number }>(`/api/ingestion/timesheets/${timesheetId}/line-items/${itemId}/reject`, { reason }),
  unrejectLineItem: (timesheetId: number, itemId: number) =>
    apiClient.post<{ status: string; line_item_id: number }>(`/api/ingestion/timesheets/${timesheetId}/line-items/${itemId}/unreject`, {}),
  revertTimesheetRejection: (id: number) =>
    apiClient.post<{ status: string }>(`/api/ingestion/timesheets/${id}/revert-rejection`, {}),
  draftComment: (id: number, seed_text: string) =>
    apiClient.post<{ draft: string }>(`/api/ingestion/timesheets/${id}/draft-comment`, { seed_text }),
};

// Platform settings endpoints (PLATFORM_ADMIN only)
export type SmtpConfigResponse = {
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password_set: boolean;
  smtp_from_address: string;
  smtp_from_name: string;
  smtp_use_tls: boolean;
  source: 'database' | 'environment';
};

export type SmtpConfigUpdate = {
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password?: string | null;
  smtp_from_address: string;
  smtp_from_name: string;
  smtp_use_tls: boolean;
};

export const platformSettingsAPI = {
  getSmtp: () => apiClient.get<SmtpConfigResponse>('/platform/settings/smtp'),
  updateSmtp: (data: SmtpConfigUpdate) => apiClient.put<SmtpConfigResponse>('/platform/settings/smtp', data),
  clearSmtp: () => apiClient.delete('/platform/settings/smtp'),
};
