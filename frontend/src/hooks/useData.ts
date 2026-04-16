import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { HistoryGroup } from '@/api/endpoints';
import {
  timeentriesAPI,
  approvalsAPI,
  clientsAPI,
  projectsAPI,
  dashboardAPI,
  notificationsAPI,
  timeOffAPI,
  timeOffApprovalsAPI,
  usersAPI,
  tasksAPI,
  tenantsAPI,
  mailboxesAPI,
  mappingsAPI,
  ingestionAPI,
  tenantSettingsAPI,
  departmentsAPI,
  leaveTypesAPI,
} from '@/api/endpoints';

type TimeEntriesListParams = Parameters<typeof timeentriesAPI.list>[0];
type ApprovalsPendingParams = Parameters<typeof approvalsAPI.pending>[0];
type ApprovalsHistoryParams = Parameters<typeof approvalsAPI.history>[0];
type ProjectsListParams = Parameters<typeof projectsAPI.list>[0];
type TasksListParams = Parameters<typeof tasksAPI.list>[0];
type TimeOffListParams = Parameters<typeof timeOffAPI.list>[0];
type TimeOffApprovalsPendingParams = Parameters<typeof timeOffApprovalsAPI.pending>[0];
type TimeOffApprovalsHistoryParams = Parameters<typeof timeOffApprovalsAPI.history>[0];
type GenericQueryParams = Record<string, unknown>;

// TimeEntries queries
export const useTimeEntries = (params?: GenericQueryParams) => {
  return useQuery({
    queryKey: ['timeentries', params],
    queryFn: () => timeentriesAPI.list(params as TimeEntriesListParams).then(res => res.data),
    placeholderData: keepPreviousData,
  });
};

export const useTimeEntry = (id: number) => {
  return useQuery({
    queryKey: ['timeentry', id],
    queryFn: () => timeentriesAPI.get(id).then(res => res.data),
  });
};

export const useParseNaturalTimeEntry = () => {
  return useMutation({
    mutationFn: (text: string) => timeentriesAPI.parseNatural(text).then(res => res.data),
  });
};

export const useCreateTimeEntry = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof timeentriesAPI.create>[0]) => timeentriesAPI.create(data).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['timeentries'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useUpdateTimeEntry = (id: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof timeentriesAPI.update>[1]) => timeentriesAPI.update(id, data).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['timeentries'] });
      queryClient.invalidateQueries({ queryKey: ['timeentry', id] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useDeleteTimeEntry = (id: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => timeentriesAPI.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['timeentries'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useSubmitTimeEntries = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entry_ids: number[]) => timeentriesAPI.submit(entry_ids).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['timeentries'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useWeeklySubmitStatus = () => {
  return useQuery({
    queryKey: ['timeentries', 'weekly-submit-status'],
    queryFn: () => timeentriesAPI.weeklySubmitStatus().then(res => res.data),
    refetchInterval: 60000,
    staleTime: 30000,
  });
};

// Approvals queries
export const usePendingApprovals = (params?: GenericQueryParams, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['approvals', 'pending', params],
    queryFn: () => approvalsAPI.pending(params as ApprovalsPendingParams).then(res => res.data),
    placeholderData: keepPreviousData,
    enabled,
  });
};

export const useApprovalHistory = (params?: GenericQueryParams) => {
  return useQuery({
    queryKey: ['approvals', 'history', params],
    queryFn: () => approvalsAPI.history(params as ApprovalsHistoryParams).then(res => res.data),
    placeholderData: keepPreviousData,
  });
};

export const useApprovalHistoryGrouped = (params?: { days_back?: number; status_filter?: string }) => {
  return useQuery<HistoryGroup[]>({
    queryKey: ['approvals', 'history-grouped', params],
    queryFn: () => approvalsAPI.historyGrouped(params).then(res => res.data),
    placeholderData: keepPreviousData,
  });
};

export const useApproveTimeEntry = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => approvalsAPI.approve(id).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] });
      queryClient.invalidateQueries({ queryKey: ['timeentries'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useRejectTimeEntry = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      approvalsAPI.reject(id, reason).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] });
      queryClient.invalidateQueries({ queryKey: ['timeentries'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useApproveTimeEntryBatch = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entryIds: number[]) => approvalsAPI.batchApprove(entryIds).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] });
      queryClient.invalidateQueries({ queryKey: ['timeentries'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useRejectTimeEntryBatch = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ entryIds, reason }: { entryIds: number[]; reason: string }) =>
      approvalsAPI.batchReject(entryIds, reason).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] });
      queryClient.invalidateQueries({ queryKey: ['timeentries'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

// Clients queries
export const useClients = () => {
  return useQuery({
    queryKey: ['clients'],
    queryFn: () => clientsAPI.list().then(res => res.data),
  });
};

export const useUpdateClient = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<{ name: string; quickbooks_customer_id: string }> }) =>
      clientsAPI.update(id, data).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clients'] });
    },
  });
};

export const useDeleteClient = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => clientsAPI.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clients'] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });
};

export const useBulkDeleteClients = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (clientIds: number[]) => clientsAPI.bulkDelete(clientIds).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clients'] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });
};

export const useDeleteProject = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => projectsAPI.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });
};

export const useCreateClient = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; quickbooks_customer_id?: string }) =>
      clientsAPI.create(data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clients'] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
};

// Projects queries
export const useProjects = (params?: GenericQueryParams) => {
  return useQuery({
    queryKey: ['projects', params],
    queryFn: () => projectsAPI.list(params as ProjectsListParams).then(res => res.data),
    placeholderData: keepPreviousData,
  });
};

export const useTasks = (params?: TasksListParams) => {
  return useQuery({
    queryKey: ['tasks', params],
    queryFn: () => tasksAPI.list(params).then(res => res.data),
    placeholderData: keepPreviousData,
  });
};

export const useCreateTask = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof tasksAPI.create>[0]) => tasksAPI.create(data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['timeentries'] });
    },
  });
};

export const useUpdateTask = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof tasksAPI.update>[1] }) => tasksAPI.update(id, data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['timeentries'] });
    },
  });
};

export const useDeleteTask = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => tasksAPI.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['timeentries'] });
    },
  });
};

export const useCreateProject = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof projectsAPI.create>[0]) => projectsAPI.create(data).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useUpdateProject = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof projectsAPI.update>[1] }) => projectsAPI.update(id, data).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useDashboardSummary = () => {
  return useQuery({
    queryKey: ['dashboard', 'summary'],
    queryFn: () => dashboardAPI.summary().then((res) => res.data),
  });
};

export const useNotifications = () => {
  return useQuery({
    queryKey: ['notifications', 'summary'],
    queryFn: () => notificationsAPI.summary().then((res) => res.data),
    placeholderData: keepPreviousData,
    refetchInterval: 60000,
    staleTime: 30000,  // Serve cached data for 30s before background refetch
  });
};

export const useMarkNotificationRead = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (notificationId: string) => notificationsAPI.markRead(notificationId).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useMarkAllNotificationsRead = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => notificationsAPI.markAllRead().then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useDeleteNotification = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (notificationId: string) => notificationsAPI.deleteOne(notificationId).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useDeleteAllNotifications = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => notificationsAPI.deleteAll().then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useTeamEmployees = () => {
  return useQuery({
    queryKey: ['dashboard', 'team'],
    queryFn: () => dashboardAPI.team().then(res => res.data),
    placeholderData: keepPreviousData,
  });
};

export const useTeamDailyOverview = () => {
  return useQuery({
    queryKey: ['dashboard', 'team-daily-overview'],
    queryFn: () => dashboardAPI.teamDailyOverview().then((res) => res.data),
    placeholderData: keepPreviousData,
    refetchInterval: 60000,
    staleTime: 30000,
  });
};

export const useDashboardAnalytics = (params: {
  start_date: string;
  end_date: string;
  project_id?: number;
  user_id?: number;
}) => {
  return useQuery({
    queryKey: ['dashboard', 'analytics', params],
    queryFn: () => dashboardAPI.analytics(params).then(res => res.data),
    enabled: !!params.start_date && !!params.end_date,
    placeholderData: keepPreviousData,
  });
};

export const useDashboardRecentActivity = (params?: { limit?: number }, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['dashboard', 'recent-activity', params],
    queryFn: () => dashboardAPI.recentActivity(params).then((res) => res.data),
    enabled,
    placeholderData: keepPreviousData,
  });
};
export const useAuditTrail = (params?: { limit?: number; offset?: number; activity_type?: string; search?: string }) => {
  return useQuery({
    queryKey: ['dashboard', 'audit-trail', params],
    queryFn: () => dashboardAPI.auditTrail(params).then((res) => res.data),
    placeholderData: keepPreviousData,
  });
};

export const useTimeOffRequests = (params?: TimeOffListParams) => {
  return useQuery({
    queryKey: ['timeoff', params],
    queryFn: () => timeOffAPI.list(params).then((res) => res.data),
    placeholderData: keepPreviousData,
  });
};

export const useTimeOffRequest = (id: number) => {
  return useQuery({
    queryKey: ['timeoff', id],
    queryFn: () => timeOffAPI.get(id).then((res) => res.data),
  });
};

export const useCreateTimeOffRequest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof timeOffAPI.create>[0]) => timeOffAPI.create(data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['timeoff'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useUpdateTimeOffRequest = (id: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof timeOffAPI.update>[1]) => timeOffAPI.update(id, data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['timeoff'] });
      queryClient.invalidateQueries({ queryKey: ['timeoff', id] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useDeleteTimeOffRequest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => timeOffAPI.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['timeoff'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useSubmitTimeOffRequests = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request_ids: number[]) => timeOffAPI.submit(request_ids).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['timeoff'] });
      queryClient.invalidateQueries({ queryKey: ['timeoff-approvals'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const usePendingTimeOffApprovals = (params?: TimeOffApprovalsPendingParams, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['timeoff-approvals', 'pending', params],
    queryFn: () => timeOffApprovalsAPI.pending(params).then((res) => res.data),
    placeholderData: keepPreviousData,
    enabled,
  });
};

export const useTimeOffApprovalHistory = (params?: TimeOffApprovalsHistoryParams) => {
  return useQuery({
    queryKey: ['timeoff-approvals', 'history', params],
    queryFn: () => timeOffApprovalsAPI.history(params).then((res) => res.data),
    placeholderData: keepPreviousData,
  });
};

export const useApproveTimeOffRequest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => timeOffApprovalsAPI.approve(id).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['timeoff-approvals'] });
      queryClient.invalidateQueries({ queryKey: ['timeoff'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useRejectTimeOffRequest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      timeOffApprovalsAPI.reject(id, reason).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['timeoff-approvals'] });
      queryClient.invalidateQueries({ queryKey: ['timeoff'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

// Users queries (Admin only)
export const useUsers = (enabled: boolean = true) => {
  return useQuery({
    queryKey: ['users'],
    queryFn: () => usersAPI.list().then((res) => res.data),
    enabled,
  });
};

export const useMyProfile = () => {
  return useQuery({
    queryKey: ['users', 'me', 'profile'],
    queryFn: () => usersAPI.meProfile().then((res) => res.data),
  });
};

export const useUpdateMyProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { full_name?: string; title?: string; department?: string; timezone?: string }) =>
      usersAPI.updateMyProfile(data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users', 'me', 'profile'] });
    },
  });
};

export const useChangePassword = () => {
  return useMutation({
    mutationFn: (data: { current_password: string; new_password: string }) =>
      usersAPI.changePassword(data).then((res) => res.data),
  });
};

export const useCreateUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof usersAPI.create>[0]) => usersAPI.create(data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useUpdateUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof usersAPI.update>[1] }) => usersAPI.update(id, data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useDeleteUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => usersAPI.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useResetUserPassword = () => {
  return useMutation({
    mutationFn: ({ id, newPassword }: { id: number; newPassword: string }) =>
      usersAPI.resetPassword(id, newPassword).then(res => res.data),
  });
};

export const useBulkDeleteUsers = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userIds: number[]) => usersAPI.bulkDelete(userIds).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
};

export const useTenants = (enabled: boolean = true) => {
  return useQuery({
    queryKey: ['tenants'],
    queryFn: () => tenantsAPI.list().then((res) => res.data),
    enabled,
  });
};

export const useTenant = (tenantId?: number | null, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['tenants', tenantId],
    queryFn: () => tenantsAPI.get(tenantId as number).then((res) => res.data),
    enabled: enabled && Boolean(tenantId),
  });
};

export const useMailboxes = (enabled: boolean = true) => {
  return useQuery({
    queryKey: ['mailboxes'],
    queryFn: () => mailboxesAPI.list().then((res) => res.data),
    enabled,
  });
};

export const useCreateMailbox = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof mailboxesAPI.create>[0]) => mailboxesAPI.create(data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mailboxes'] });
    },
  });
};

export const useUpdateMailbox = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof mailboxesAPI.update>[1] }) =>
      mailboxesAPI.update(id, data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mailboxes'] });
    },
  });
};

export const useDeleteMailbox = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => mailboxesAPI.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mailboxes'] });
    },
  });
};

export const useTestMailbox = () => {
  return useMutation({
    mutationFn: (id: number) => mailboxesAPI.test(id).then((res) => res.data),
  });
};

export const useResetMailboxCursor = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => mailboxesAPI.resetCursor(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mailboxes'] });
    },
  });
};

export const useMappings = (enabled: boolean = true) => {
  return useQuery({
    queryKey: ['mappings'],
    queryFn: () => mappingsAPI.list().then((res) => res.data),
    enabled,
  });
};

export const useCreateMapping = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof mappingsAPI.create>[0]) => mappingsAPI.create(data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mappings'] });
    },
  });
};

export const useUpdateMapping = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof mappingsAPI.update>[1] }) =>
      mappingsAPI.update(id, data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mappings'] });
    },
  });
};

export const useDeleteMapping = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => mappingsAPI.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mappings'] });
    },
  });
};

export const useBulkDeleteMappings = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (mappingIds: number[]) => mappingsAPI.bulkDelete(mappingIds).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mappings'] });
    },
  });
};

export const useTriggerFetchEmails = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => ingestionAPI.triggerFetch().then((res) => res.data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'fetch-status', data.job_id] });
    },
  });
};

export const useReprocessSkippedEmails = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => ingestionAPI.reprocessSkipped().then((res) => res.data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'fetch-status', data.job_id] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'skipped-emails'] });
    },
  });
};

export const useReprocessIngestionEmail = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ emailId, attachmentIds }: { emailId: number; attachmentIds?: number[] }) =>
      ingestionAPI.reprocessEmail(emailId, attachmentIds).then((res) => res.data),
    onError: () => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'skipped-emails'] });
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'fetch-status', data.job_id] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'skipped-emails'] });
    },
  });
};

export const useDeleteIngestedEmail = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ emailId, refetch = false }: { emailId: number; refetch?: boolean }) =>
      ingestionAPI.deleteEmail(emailId, refetch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'skipped-emails'] });
    },
  });
};

export const useBulkReprocessEmails = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (emailIds: number[]) => ingestionAPI.bulkReprocess(emailIds).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'skipped-emails'] });
    },
  });
};

export const useBulkDeleteIngestedEmails = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (emailIds: number[]) => ingestionAPI.bulkDeleteEmails(emailIds).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'skipped-emails'] });
    },
  });
};

export const useReapplyIngestionMappings = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => ingestionAPI.reapplyMappings().then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
    },
  });
};

export const useSkippedEmails = (limit: number = 10, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['ingestion', 'skipped-emails', limit],
    queryFn: () => ingestionAPI.getSkippedEmails({ limit }).then((res) => res.data),
    enabled,
  });
};

export const useFetchJobStatus = (jobId?: string | null, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['ingestion', 'fetch-status', jobId],
    queryFn: () => ingestionAPI.getFetchStatus(jobId as string).then((res) => res.data),
    enabled: enabled && Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'in_progress' ? 4000 : false;
    },
  });
};

export const useIngestionTimesheets = (params?: Parameters<typeof ingestionAPI.listTimesheets>[0], enabled: boolean = true) => {
  return useQuery({
    queryKey: ['ingestion', 'timesheets', params],
    queryFn: () => ingestionAPI.listTimesheets(params).then((res) => res.data),
    enabled,
    placeholderData: keepPreviousData,
  });
};

export const useIngestionTimesheet = (id?: number | null, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['ingestion', 'timesheet', id],
    queryFn: () => ingestionAPI.getTimesheet(id as number).then((res) => res.data),
    enabled: enabled && Boolean(id),
  });
};

export const useIngestionEmail = (emailId?: number | null, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['ingestion', 'email', emailId],
    queryFn: () => ingestionAPI.getEmail(emailId as number).then((res) => res.data),
    enabled: enabled && Boolean(emailId),
  });
};

export const useUpdateIngestionTimesheetData = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof ingestionAPI.updateTimesheetData>[1] }) =>
      ingestionAPI.updateTimesheetData(id, data).then((res) => res.data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheet', id] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
    },
  });
};

export const useAddIngestionLineItem = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ timesheetId, data }: { timesheetId: number; data: Parameters<typeof ingestionAPI.addLineItem>[1] }) =>
      ingestionAPI.addLineItem(timesheetId, data).then((res) => res.data),
    onSuccess: (_, { timesheetId }) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheet', timesheetId] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
    },
  });
};

export const useUpdateIngestionLineItem = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      timesheetId,
      itemId,
      data,
    }: {
      timesheetId: number;
      itemId: number;
      data: Parameters<typeof ingestionAPI.updateLineItem>[2];
    }) => ingestionAPI.updateLineItem(timesheetId, itemId, data).then((res) => res.data),
    onSuccess: (_, { timesheetId }) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheet', timesheetId] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
    },
  });
};

export const useDeleteIngestionLineItem = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ timesheetId, itemId }: { timesheetId: number; itemId: number }) =>
      ingestionAPI.deleteLineItem(timesheetId, itemId),
    onSuccess: (_, { timesheetId }) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheet', timesheetId] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
    },
  });
};

export const useApproveIngestionTimesheet = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, comment }: { id: number; comment?: string }) =>
      ingestionAPI.approveTimesheet(id, comment).then((res) => res.data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheet', id] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
      queryClient.invalidateQueries({ queryKey: ['timeentries'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
};

export const useRejectIngestionTimesheet = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason, comment }: { id: number; reason: string; comment?: string }) =>
      ingestionAPI.rejectTimesheet(id, reason, comment).then((res) => res.data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheet', id] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
    },
  });
};

export const useHoldIngestionTimesheet = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, comment }: { id: number; comment?: string }) =>
      ingestionAPI.holdTimesheet(id, comment).then((res) => res.data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheet', id] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
    },
  });
};

export const useDraftIngestionComment = () => {
  return useMutation({
    mutationFn: ({ id, seedText }: { id: number; seedText: string }) =>
      ingestionAPI.draftComment(id, seedText).then((res) => res.data),
  });
};

export const useRejectIngestionLineItem = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ timesheetId, itemId, reason }: { timesheetId: number; itemId: number; reason: string }) =>
      ingestionAPI.rejectLineItem(timesheetId, itemId, reason).then((res) => res.data),
    onSuccess: (_, { timesheetId }) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheet', timesheetId] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
    },
  });
};

export const useUnrejectIngestionLineItem = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ timesheetId, itemId }: { timesheetId: number; itemId: number }) =>
      ingestionAPI.unrejectLineItem(timesheetId, itemId).then((res) => res.data),
    onSuccess: (_, { timesheetId }) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheet', timesheetId] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
    },
  });
};

export const useRevertIngestionTimesheetRejection = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: number }) =>
      ingestionAPI.revertTimesheetRejection(id).then((res) => res.data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheet', id] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
    },
  });
};

export const useRevertTimeEntryRejection = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: number }) =>
      approvalsAPI.revertRejection(id).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals', 'history'] });
      queryClient.invalidateQueries({ queryKey: ['approvals', 'pending'] });
    },
  });
};

// ── Tenant Settings ────────────────────────────────────────────────────────

export const useTenantSettings = (enabled: boolean = true) => {
  return useQuery({
    queryKey: ['tenant-settings'],
    queryFn: () => tenantSettingsAPI.get().then((res) => res.data),
    enabled,
  });
};

export const useTenantPublicSettings = () => {
  return useQuery({
    queryKey: ['tenant-settings', 'public'],
    queryFn: () => tenantSettingsAPI.getPublic().then((res) => res.data),
  });
};

/** Resolve tenant week start day as a date-fns compatible 0|1. Defaults to 0 (Sunday). */
export const useWeekStartsOn = (): 0 | 1 => {
  const { data } = useTenantPublicSettings();
  return data?.week_start_day === '1' ? 1 : 0;
};

export const useUpdateTenantSettings = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, string | null>) =>
      tenantSettingsAPI.update(data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tenant-settings'] });
      queryClient.invalidateQueries({ queryKey: ['tenant-settings', 'public'] });
    },
  });
};

export const useUnlockUserTimesheet = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: number) => tenantSettingsAPI.unlockUser(userId).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });
};

// ── Departments ────────────────────────────────────────────────────────────

export const useDepartments = () => {
  return useQuery({
    queryKey: ['departments'],
    queryFn: () => departmentsAPI.list().then((res) => res.data),
  });
};

export const useCreateDepartment = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => departmentsAPI.create(name).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['departments'] });
    },
  });
};

export const useDeleteDepartment = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => departmentsAPI.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['departments'] });
    },
  });
};

// ── Leave types ────────────────────────────────────────────────────────────

export const useLeaveTypes = (includeInactive = false) => {
  return useQuery({
    queryKey: ['leave-types', includeInactive],
    queryFn: () => leaveTypesAPI.list(includeInactive).then((r) => r.data),
  });
};

export const useCreateLeaveType = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { label: string; code?: string; color?: string }) =>
      leaveTypesAPI.create(data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['leave-types'] });
    },
  });
};

export const useUpdateLeaveType = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: { label?: string; color?: string; is_active?: boolean } }) =>
      leaveTypesAPI.update(id, data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['leave-types'] });
    },
  });
};

export const useDeleteLeaveType = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => leaveTypesAPI.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['leave-types'] });
    },
  });
};
