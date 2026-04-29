import React, { useEffect, useMemo, useRef, useState } from 'react';
import { addWeeks, differenceInCalendarWeeks, endOfWeek, format, isThisWeek, parseISO, startOfWeek } from 'date-fns';
import { Calendar, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Loading, Error, ChangePasswordModal, AdminActionQueue, SystemHealthCard, WeeklyRoster, ManagerConversation, ManagerGlanceTiles, ProjectHealthTable, QuickLogButton } from '@/components';
import type { SystemHealthStatus } from '@/components/SystemHealthCard';
import {
  useAuth,
  useChangePassword,
  useClients,
  useDashboardAnalytics,
  useDashboardRecentActivity,
  useNotifications,
  useProjects,
  useTeamDailyOverview,
  useTeamEmployees,
  useTenants,
  useUsers,
  useIngestionTimesheets,
  useCanReview,
  useIngestionEnabled,
  useWeekStartsOn,
  useAdminSystemHealth,
  useManagerTeamOverview,
  useManagerProjectHealth,
} from '@/hooks';
import type { DashboardActivity, DashboardBarEntryDetail, DashboardDayBreakdown, DashboardProjectBreakdown, DashboardRecentActivityItem, NotificationItem, Project, TeamDailyOverview, Tenant, User } from '@/types';

const PROJECT_COLORS = ['#7b5748', '#4f772d', '#355070', '#bc6c25', '#2a9d8f', '#6d597a', '#e76f51', '#457b9d'];

const toNumber = (value: string | number) => (typeof value === 'string' ? parseFloat(value) : value);

const formatHours = (value: number) => {
  const safeValue = Number.isFinite(value) ? value : 0;
  const hours = Math.floor(safeValue);
  const minutes = Math.round((safeValue - hours) * 60);

  if (hours === 0 && minutes === 0) {
    return '00:00';
  }

  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
};

const getLatestWorkingDate = (input: Date): Date => {
  const reference = new Date(input);
  while (reference.getDay() === 0 || reference.getDay() === 6) {
    reference.setDate(reference.getDate() - 1);
  }
  return reference;
};

type SelectedBarSegment = {
  projectName: string;
  clientName: string;
  entryDate: string;
  totalHours: number;
  entries: DashboardBarEntryDetail[];
};

type AdminStatsTileKey = 'active-users' | 'employees' | 'managers' | 'admins' | 'clients' | 'active-projects' | 'notifications' | 'pending-reviews';

const getAdminTileActionLabel = (tileKey: AdminStatsTileKey) => {
  if (tileKey === 'active-users') return 'Opens User Management filtered to Active users.';
  if (tileKey === 'employees') return 'Opens User Management filtered to Employees.';
  if (tileKey === 'managers') return 'Opens User Management filtered to Managers.';
  if (tileKey === 'admins') return 'Opens User Management filtered to Admins.';
  if (tileKey === 'clients') return 'Opens Client Management.';
  if (tileKey === 'active-projects') return 'Opens Client Management in Projects view filtered to Active projects.';
  if (tileKey === 'pending-reviews') return 'Opens Email Inbox to review pending timesheets.';
  return 'Opens notifications dialog.';
};

const getActivitySeverityClasses = (severity: string) => {
  if (severity === 'error') return 'bg-red-100 text-red-700';
  if (severity === 'warning') return 'bg-amber-100 text-amber-700';
  if (severity === 'success') return 'bg-emerald-100 text-emerald-700';
  return 'bg-slate-100 text-slate-700';
};

const getActivitySeverityLabel = (severity: string) => {
  if (severity === 'error') return 'Alert';
  if (severity === 'warning') return 'Notice';
  if (severity === 'success') return 'Done';
  return 'Info';
};

const buildRouteWithParams = (
  route: string,
  params?: Record<string, string | number | boolean | null> | null,
) => {
  if (!params) return route;

  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === '') return;
    searchParams.set(key, String(value));
  });

  const query = searchParams.toString();
  return query ? `${route}?${query}` : route;
};

const DashboardBarChart: React.FC<{
  data: DashboardDayBreakdown[];
  projectColorMap: Record<number, string>;
  onSelectSegment: (segment: SelectedBarSegment) => void;
}> = ({ data, projectColorMap, onSelectSegment }) => {
  const maxValue = Math.max(...data.map((item) => toNumber(item.hours)), 0.01);
  const [hoverText, setHoverText] = useState<string>('');

  return (
    <>
      {hoverText && (
        <div className="mb-3 text-xs text-muted-foreground">{hoverText}</div>
      )}
      <div className="grid grid-cols-7 gap-3 items-end h-72">
        {data.map((item) => {
          const value = toNumber(item.hours);
          const height = value <= 0 ? 2 : Math.max((value / maxValue) * 220, 12);
          const [weekday, monthDay] = item.formatted_date.split(', ');

          return (
            <div key={item.entry_date} className="flex flex-col items-center justify-end h-full">
              <span className="text-xs text-muted-foreground mb-2">{formatHours(value)}</span>
              <div className="w-full flex items-end justify-center h-56">
                <div
                  className="w-full max-w-[88px] rounded-t-md overflow-hidden flex flex-col-reverse"
                  style={{ height }}
                >
                  {item.segments.length === 0 ? (
                    <div className="w-full h-[2px] bg-[#7b5748]" />
                  ) : (
                    item.segments.map((segment) => {
                      const segmentHours = toNumber(segment.hours);
                      const segmentHeight = Math.max((segmentHours / maxValue) * 220, 8);
                      const firstEntry = segment.entries[0];
                      return (
                        <button
                          type="button"
                          key={`${item.entry_date}-${segment.project_id}`}
                          onMouseEnter={() => setHoverText(`${segment.project_name}: ${formatHours(segmentHours)}`)}
                          onMouseLeave={() => setHoverText('')}
                          onClick={() => {
                            if (firstEntry) {
                              onSelectSegment({
                                projectName: segment.project_name,
                                clientName: segment.client_name,
                                entryDate: item.entry_date,
                                totalHours: segmentHours,
                                entries: segment.entries,
                              });
                            }
                          }}
                          className="w-full"
                          style={{
                            height: segmentHeight,
                            backgroundColor: projectColorMap[segment.project_id] ?? PROJECT_COLORS[0],
                          }}
                          title={`${segment.project_name} • ${formatHours(segmentHours)}`}
                        />
                      );
                    })
                  )}
                </div>
              </div>
              <span className="mt-3 text-xs text-foreground text-center">{weekday}</span>
              <span className="text-[11px] text-muted-foreground text-center">{monthDay}</span>
            </div>
          );
        })}
      </div>
    </>
  );
};

const DashboardDonutChart: React.FC<{ data: DashboardProjectBreakdown[]; totalHours: number }> = ({ data, totalHours }) => {
  const radius = 70;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  if (data.length === 0) {
    return (
      <div className="relative h-56 w-56 shrink-0">
        <svg viewBox="0 0 200 200" className="h-full w-full -rotate-90">
          <circle cx="100" cy="100" r={radius} fill="none" stroke="#e5e7eb" strokeWidth="36" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-bold">00:00</span>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-56 w-56 shrink-0">
      <svg viewBox="0 0 200 200" className="h-full w-full -rotate-90">
        {data.map((item, index) => {
          const segment = (item.percentage / 100) * circumference;
          const circle = (
            <circle
              key={item.project_id}
              cx="100"
              cy="100"
              r={radius}
              fill="none"
              stroke={PROJECT_COLORS[index % PROJECT_COLORS.length]}
              strokeWidth="36"
              strokeDasharray={`${segment} ${circumference - segment}`}
              strokeDashoffset={-offset}
            />
          );
          offset += segment;
          return circle;
        })}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold">{formatHours(totalHours)}</span>
      </div>
    </div>
  );
};

// Collapsible roster card: summary pills always visible, click the
// header to expand into the per-person WeeklyRoster. Lives inside the
// page file because it's tightly coupled to the manager view layout.
const ManagerTeamRosterCard: React.FC<{
  overview: import('@/types').ManagerTeamOverviewResponse | undefined;
  loading: boolean;
  selectedUserId: number | null;
  onSelect: (userId: number) => void;
}> = ({ overview, loading, selectedUserId, onSelect }) => {
  const [open, setOpen] = useState(false);
  if (loading && !overview) {
    return <div className="rounded-lg border bg-card p-5 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)] text-sm text-muted-foreground">Loading roster...</div>;
  }
  const members = overview?.members ?? [];
  const counts = members.reduce(
    (acc, m) => {
      if (m.is_repeatedly_late) acc.critical += 1;
      else if (m.is_on_pto_today) acc.pto += 1;
      else if (m.working_days_in_week > 0 && m.submitted_days < m.working_days_in_week) acc.behind += 1;
      else acc.ontrack += 1;
      return acc;
    },
    { critical: 0, behind: 0, pto: 0, ontrack: 0 },
  );
  const total = members.length;
  const pill = (cls: string, n: number, label: string) => (
    <span
      key={label}
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${cls}`}
      style={{ opacity: n === 0 ? 0.5 : 1 }}
    >
      {n} {label}
    </span>
  );
  const weekRange = overview ? `${format(parseISO(overview.week_start), 'MMM d')} - ${format(parseISO(overview.week_end), 'MMM d')}` : '';

  return (
    <div className={`rounded-lg border bg-card mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)] overflow-hidden ${open ? '' : 'manager-roster-collapsed'}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-4 px-5 py-4 text-left hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset"
      >
        <div className="flex flex-col">
          <span className="text-base font-semibold">This week — team status</span>
          <span className="text-xs text-muted-foreground">{weekRange}</span>
        </div>
        <div className="ml-auto flex items-center gap-2 flex-wrap justify-end">
          {pill('bg-red-500/15 text-red-700 dark:text-red-300', counts.critical, 'critical')}
          {pill('bg-amber-500/15 text-amber-700 dark:text-amber-300', counts.behind, 'behind')}
          {pill('bg-sky-500/15 text-sky-700 dark:text-sky-300', counts.pto, 'on PTO')}
          {pill('bg-emerald-500/15 text-emerald-700 dark:text-emerald-300', counts.ontrack, `of ${total} on track`)}
        </div>
        <span className="ml-2 text-xs text-muted-foreground transition-transform" style={{ transform: open ? 'rotate(180deg)' : undefined }}>
          ▼
        </span>
      </button>
      {open && (
        <div className="border-t border-border px-5 pt-4 pb-5">
          <WeeklyRoster
            members={members}
            selectedUserId={selectedUserId}
            onSelectEmployee={onSelect}
          />
        </div>
      )}
    </div>
  );
};

export const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const { user, refreshUser } = useAuth();
  const changePassword = useChangePassword();
  const [weekOffset, setWeekOffset] = useState(0);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [selectedBarSegment, setSelectedBarSegment] = useState<SelectedBarSegment | null>(null);
  const [adminDashboardView, setAdminDashboardView] = useState<'stats' | 'my-time'>('stats');
  const [managerDashboardView, setManagerDashboardView] = useState<'team' | 'my-time'>('team');
  const [isNotificationsModalOpen, setIsNotificationsModalOpen] = useState(false);
  const [isPasswordChangeModalOpen, setIsPasswordChangeModalOpen] = useState(false);
  const [showWeekPicker, setShowWeekPicker] = useState(false);
  const [showRecentActivity, setShowRecentActivity] = useState(false);
  const weekStartsOn = useWeekStartsOn();
  const [pickerMonth, setPickerMonth] = useState<Date>(() => new Date());

  useEffect(() => {
    if (user) {
      setIsPasswordChangeModalOpen(!user.has_changed_password);
    }
  }, [user]);

  useEffect(() => {
    void refreshUser();
  }, [refreshUser]);

  const isManagerView = user?.role === 'MANAGER' || user?.role === 'SENIOR_MANAGER';
  const isPlatformAdmin = user?.role === 'PLATFORM_ADMIN';
  const isAdminView = user?.role === 'ADMIN';
  const showProjectClientWidgets = !isAdminView && !isPlatformAdmin;
  const showAdminStatsView = isPlatformAdmin || (isAdminView && adminDashboardView === 'stats');
  // Personal-time view (bar chart, donut, top activities) is the
  // default for non-manager / non-admin roles. For managers it's only
  // visible when they explicitly switch to My Time. For admins, only
  // when admin My Time is selected. The manager Team tab now has its
  // own redesigned layout and should not also show personal-time
  // widgets below it.
  const showPersonalTimeView = (
    (!isAdminView && !isPlatformAdmin && !isManagerView)
    || (isAdminView && adminDashboardView === 'my-time')
    || (isManagerView && managerDashboardView === 'my-time')
  );
  const showManagerTeamSection = isManagerView && managerDashboardView === 'team';

  const weekRange = useMemo(() => {
    const managerReference = isManagerView ? getLatestWorkingDate(new Date()) : new Date();
    const referenceDate = addWeeks(managerReference, weekOffset);
    const start = startOfWeek(referenceDate, { weekStartsOn });
    const end = endOfWeek(referenceDate, { weekStartsOn });

    return {
      startDate: format(start, 'yyyy-MM-dd'),
      endDate: format(end, 'yyyy-MM-dd'),
      label: isThisWeek(referenceDate, { weekStartsOn })
        ? 'This week'
        : `${format(start, 'MMM d')} - ${format(end, 'MMM d')}`,
    };
  }, [isManagerView, weekOffset]);

  const { data: projects = [], isLoading: projectsLoading } = useProjects({ active_only: true });
  const { data: teamEmployees = [], isLoading: teamLoading } = useTeamEmployees();
  const { data: teamDailyOverview, isLoading: teamDailyLoading } = useTeamDailyOverview();
  const { data: users = [], isLoading: usersLoading, error: usersError } = useUsers(isAdminView);
  const { data: tenants = [], isLoading: tenantsLoading, error: tenantsError } = useTenants(isPlatformAdmin);
  const { data: clients = [], isLoading: clientsLoading, error: clientsError } = useClients();
  const { data: notificationsSummary, isLoading: notificationsLoading, error: notificationsError, isFetching: notificationsFetching, isError: notificationsIsError } = useNotifications();
  const canReview = useCanReview();
  const ingestionEnabled = useIngestionEnabled();
  const { data: pendingTimesheets = [] } = useIngestionTimesheets(
    { status_filter: 'pending', limit: 200 },
    canReview && ingestionEnabled,
  );
  const pendingReviewCount = pendingTimesheets.length;
  const { data: recentActivity = [], isLoading: recentActivityLoading, error: recentActivityError } = useDashboardRecentActivity({ limit: 12 }, showAdminStatsView);
  // Live infra health for the admin dashboard. Polls every 30s while
  // the admin stats view is mounted; idle otherwise.
  const { data: systemHealth, isLoading: systemHealthLoading } = useAdminSystemHealth(showAdminStatsView);
  // Manager view overview (week-to-date roster + capacity). Only the
  // manager Team tab uses it; nobody else pays for the query.
  const { data: managerOverview, isLoading: managerOverviewLoading } = useManagerTeamOverview(isManagerView && managerDashboardView === 'team');
  const { data: managerProjectHealth, isLoading: managerProjectHealthLoading } = useManagerProjectHealth(isManagerView && managerDashboardView === 'team');
  const { data: analytics, isLoading: analyticsLoading, error: analyticsError } = useDashboardAnalytics({
    start_date: weekRange.startDate,
    end_date: weekRange.endDate,
    project_id: showProjectClientWidgets ? selectedProjectId ?? undefined : undefined,
    user_id: isAdminView
      ? selectedUserId ?? user?.id
      : (isManagerView && managerDashboardView === 'my-time')
        ? user?.id
        : selectedUserId ?? undefined,
  });

  const dailyBreakdown = useMemo(() => analytics?.daily_breakdown ?? [], [analytics?.daily_breakdown]);
  const projectBreakdown = useMemo(() => analytics?.project_breakdown ?? [], [analytics?.project_breakdown]);
  const topActivities = analytics?.top_activities ?? [];
  const projectColorMap = useMemo(() => {
    const map: Record<number, string> = {};
    projectBreakdown.forEach((project: DashboardProjectBreakdown, index: number) => {
      map[project.project_id] = PROJECT_COLORS[index % PROJECT_COLORS.length];
    });
    dailyBreakdown.forEach((day) => {
      day.segments.forEach((segment) => {
        if (!map[segment.project_id]) {
          const colorIndex = Object.keys(map).length % PROJECT_COLORS.length;
          map[segment.project_id] = PROJECT_COLORS[colorIndex];
        }
      });
    });
    return map;
  }, [projectBreakdown, dailyBreakdown]);

  if (!user || (!isPlatformAdmin && analyticsLoading) || (!isPlatformAdmin && projectsLoading) || ((isManagerView || isAdminView) && teamLoading) || (isManagerView && teamDailyLoading) || (isPlatformAdmin && tenantsLoading)) {
    return <Loading />;
  }

  if (analyticsError || recentActivityError || tenantsError || usersError || clientsError) {
    return <Error message="Something went wrong loading your dashboard. Please refresh." />;
  }

  const projectOptions = projects as Project[];
  const employeeOptions = teamEmployees as User[];
  const selectedEmployeeName = selectedUserId === null
    ? null
    : employeeOptions.find((employee) => employee.id === selectedUserId)?.full_name ?? null;
  const totalHours = toNumber(analytics?.total_hours ?? 0);
  const billableHours = toNumber(analytics?.billable_hours ?? 0);
  const nonBillableHours = toNumber(analytics?.non_billable_hours ?? 0);
  const allUsers = users as User[];
  const allTenants = tenants as Tenant[];
  const allClients = clients as { id: number }[];
  const activeProjectCount = projectOptions.length;
  const notificationItems = notificationsSummary?.items ?? [];

  const activeUsersCount = allUsers.filter((member) => member.is_active).length;
  const employeesCount = allUsers.filter((member) => member.role === 'EMPLOYEE').length;
  const managersCount = allUsers.filter((member) => member.role === 'MANAGER').length;
  const adminsCount = allUsers.filter((member) => member.role === 'ADMIN').length;
  const totalNotifications = notificationsSummary?.total_count ?? 0;

  const adminStatsTiles: { key: AdminStatsTileKey; label: string; value: number }[] = [
    { key: 'active-users', label: 'Active Users', value: activeUsersCount },
    { key: 'employees', label: 'Employees', value: employeesCount },
    { key: 'managers', label: 'Managers', value: managersCount },
    { key: 'admins', label: 'Admins', value: adminsCount },
    { key: 'clients', label: 'Clients', value: allClients.length },
    { key: 'active-projects', label: 'Active Projects', value: activeProjectCount },
    { key: 'notifications', label: 'Notifications', value: totalNotifications },
    ...(canReview && ingestionEnabled ? [{ key: 'pending-reviews' as AdminStatsTileKey, label: 'Pending Reviews', value: pendingReviewCount }] : []),
  ];

  const platformStatsTiles = [
    { label: 'Total Tenants', value: allTenants.length },
    { label: 'Active', value: allTenants.filter((t) => t.status === 'active').length },
    { label: 'Inactive', value: allTenants.filter((t) => t.status === 'inactive').length },
    { label: 'Suspended', value: allTenants.filter((t) => t.status === 'suspended').length },
  ];

  const handleAdminTileClick = (tileKey: AdminStatsTileKey) => {
    if (tileKey === 'active-users') {
      navigate('/user-management?status=ACTIVE');
      return;
    }
    if (tileKey === 'employees') {
      navigate('/user-management?role=EMPLOYEE');
      return;
    }
    if (tileKey === 'managers') {
      navigate('/user-management?role=MANAGER');
      return;
    }
    if (tileKey === 'admins') {
      navigate('/user-management?role=ADMIN');
      return;
    }
    if (tileKey === 'clients') {
      navigate('/client-management');
      return;
    }
    if (tileKey === 'active-projects') {
      navigate('/client-management?view=projects&status=ACTIVE');
      return;
    }
    if (tileKey === 'pending-reviews') {
      navigate('/ingestion/inbox');
      return;
    }
    setIsNotificationsModalOpen(true);
  };

  const handleAdminTileKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, tileKey: AdminStatsTileKey) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      handleAdminTileClick(tileKey);
    }
  };

  return (
    <div className="space-y-6">
       <ChangePasswordModal
         isOpen={isPasswordChangeModalOpen}
         onClose={() => setIsPasswordChangeModalOpen(false)}
         onSubmit={async (currentPassword, newPassword) => {
           await changePassword.mutateAsync({
             current_password: currentPassword,
             new_password: newPassword,
           });
           await refreshUser();
           setIsPasswordChangeModalOpen(false);
         }}
         isLoading={changePassword.isPending}
       />
       <div>
        <div className="flex items-center justify-between gap-4 mb-6 flex-wrap">
          <h1 className="text-3xl font-bold">Dashboard</h1>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Universal quick-log: every user can log time from any
                dashboard view. Sits as a popover-from-button so it
                doesn't compete with the dashboard's read content. */}
            <QuickLogButton className="relative" />
            {isManagerView && (
              <div className="flex items-center rounded-md border bg-card overflow-hidden">
                <button
                  type="button"
                  onClick={() => setManagerDashboardView('team')}
                  className={`h-10 px-4 text-sm ${managerDashboardView === 'team' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}
                >
                  Team
                </button>
                <button
                  type="button"
                  onClick={() => setManagerDashboardView('my-time')}
                  className={`h-10 px-4 text-sm border-l ${managerDashboardView === 'my-time' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}
                >
                  My Time
                </button>
              </div>
            )}

            {isAdminView && (
              <div className="flex items-center rounded-md border bg-card overflow-hidden">
                <button
                  type="button"
                  onClick={() => setAdminDashboardView('stats')}
                  className={`h-10 px-4 text-sm ${adminDashboardView === 'stats' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}
                >
                  Organization Stats
                </button>
                <button
                  type="button"
                  onClick={() => setAdminDashboardView('my-time')}
                  className={`h-10 px-4 text-sm border-l ${adminDashboardView === 'my-time' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}
                >
                  My Time
                </button>
              </div>
            )}

            {showPersonalTimeView && (
              <>
            {showProjectClientWidgets && (
              <select
                value={selectedProjectId ?? ''}
                onChange={(event) => setSelectedProjectId(event.target.value ? Number(event.target.value) : null)}
                className="h-10 rounded-md border bg-card px-3 text-sm"
              >
                <option value="">Project</option>
                {projectOptions.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            )}

            {(!isManagerView || showManagerTeamSection) && (
              <select
                value={selectedUserId ?? ''}
                onChange={(event) => setSelectedUserId(event.target.value ? Number(event.target.value) : null)}
                disabled={!isManagerView && !isAdminView}
                className="h-10 rounded-md border bg-card px-3 text-sm disabled:opacity-100 disabled:text-foreground"
              >
                <option value="">{isManagerView ? 'All team' : 'Only me'}</option>
                {(isManagerView || isAdminView) && employeeOptions.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.full_name}
                  </option>
                ))}
              </select>
            )}

            <div className="relative">
              {showWeekPicker && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setShowWeekPicker(false)} />
                  <div className="absolute top-full left-1/2 -translate-x-1/2 z-50 mt-1 bg-white border border-border rounded-xl shadow-lg p-3 select-none" style={{ minWidth: 280 }} onClick={(e) => e.stopPropagation()}>
                    {/* Month navigation */}
                    <div className="flex items-center justify-between mb-2">
                      <button type="button" className="p-1 rounded hover:bg-muted" onClick={() => setPickerMonth((m) => { const d = new Date(m); d.setMonth(d.getMonth() - 1); return d; })}>
                        <ChevronLeft className="h-4 w-4" />
                      </button>
                      <span className="text-sm font-semibold">{format(pickerMonth, 'MMMM yyyy')}</span>
                      <button type="button" className="p-1 rounded hover:bg-muted" onClick={() => setPickerMonth((m) => { const d = new Date(m); d.setMonth(d.getMonth() + 1); return d; })}>
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </div>
                    {/* Day headers */}
                    <div className="grid grid-cols-7 mb-1">
                      {['Su','Mo','Tu','We','Th','Fr','Sa'].map((d) => (
                        <div key={d} className="text-center text-[11px] font-medium text-slate-400 py-1">{d}</div>
                      ))}
                    </div>
                    {/* Day grid */}
                    {(() => {
                      const monthStart = new Date(pickerMonth.getFullYear(), pickerMonth.getMonth(), 1);
                      const gridStart = startOfWeek(monthStart, { weekStartsOn });
                      const currentWeekStart = parseISO(weekRange.startDate);
                      const managerReference = isManagerView ? getLatestWorkingDate(new Date()) : new Date();
                      const anchorWeekStart = startOfWeek(managerReference, { weekStartsOn });
                      const days: React.ReactNode[] = [];
                      for (let i = 0; i < 42; i++) {
                        const day = new Date(gridStart);
                        day.setDate(gridStart.getDate() + i);
                        const weekStart = startOfWeek(day, { weekStartsOn });
                        const weekEnd = endOfWeek(day, { weekStartsOn });
                        const isCurrentMonth = day.getMonth() === pickerMonth.getMonth();
                        const isInSelectedWeek = day >= currentWeekStart && day <= new Date(weekRange.endDate + 'T00:00:00');
                        days.push(
                          <button
                            key={i}
                            type="button"
                            onClick={() => {
                              const diff = differenceInCalendarWeeks(weekStart, anchorWeekStart, { weekStartsOn });
                              setWeekOffset(diff);
                              setShowWeekPicker(false);
                            }}
                            className={`text-center text-xs py-1.5 rounded transition
                              ${isInSelectedWeek ? 'bg-primary text-primary-foreground font-semibold' : `hover:bg-muted ${!isCurrentMonth ? 'text-slate-300' : 'text-slate-700'}`}
                            `}
                            title={`Week of ${format(weekStart, 'MMM d')} – ${format(weekEnd, 'MMM d')}`}
                          >
                            {day.getDate()}
                          </button>
                        );
                      }
                      return <div className="grid grid-cols-7 gap-y-0.5">{days}</div>;
                    })()}
                  </div>
                </>
              )}
              <div className="flex items-center rounded-md border bg-card overflow-hidden">
                <button
                  type="button"
                  onClick={() => setWeekOffset((current) => current - 1)}
                  className="h-10 w-10 flex items-center justify-center hover:bg-muted border-r"
                  aria-label="Previous week"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setShowWeekPicker((v) => !v)}
                  className="h-10 px-3 text-sm min-w-[150px] flex items-center justify-center gap-1.5 hover:bg-muted transition"
                  title="Jump to week"
                >
                  <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
                  {weekRange.label}
                </button>
                <button
                  type="button"
                  onClick={() => setWeekOffset((current) => Math.min(current + 1, 0))}
                  className="h-10 w-10 border-l flex items-center justify-center hover:bg-muted disabled:opacity-40"
                  aria-label="Next week"
                  disabled={weekOffset === 0}
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
              </>
            )}
          </div>
        </div>

        {showAdminStatsView && (
          <>
            {isAdminView && !isPlatformAdmin && (
              <AdminActionQueue
                pendingTimesheets={pendingTimesheets}
                ingestionEnabled={ingestionEnabled}
                canReview={canReview}
                notifications={notificationItems as NotificationItem[]}
                recentActivity={recentActivity}
                recentActivityLoading={recentActivityLoading}
                onOpenNotifications={() => setIsNotificationsModalOpen(true)}
              />
            )}

            {/* System Health: per-service operational state from
                /admin/system-health. Each card renders with a freshness
                subtitle and a synthetic-deterministic sparkline strip.
                The sparkline is decorative for now (no per-service time
                series endpoint yet); the chip color and subtitle carry
                the real signal. */}
            <div className="rounded-lg bg-card p-5 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-lg font-semibold">System Health</h2>
                <span className="text-xs text-muted-foreground">last 24h</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {(systemHealth ?? []).map((check) => {
                  const status: SystemHealthStatus = systemHealthLoading
                    ? 'loading'
                    : check.status === 'attention' ? 'attention' : 'healthy';
                  const sparkline = (() => {
                    if (status === 'loading') return undefined;
                    let h = 0;
                    for (let i = 0; i < check.key.length; i++) h = (h * 31 + check.key.charCodeAt(i)) >>> 0;
                    const out: number[] = [];
                    for (let i = 0; i < 24; i++) {
                      h = (h * 1664525 + 1013904223) >>> 0;
                      const base = 0.55 + ((h % 1000) / 1000) * 0.4;
                      out.push(base);
                    }
                    if (status === 'attention') out[out.length - 1] = 0.18;
                    return out;
                  })();
                  return (
                    <SystemHealthCard
                      key={check.key}
                      label={check.label}
                      status={status}
                      subtitle={check.subtitle}
                      sparkline={sparkline}
                    />
                  );
                })}
                {systemHealthLoading && !systemHealth && (
                  // First-load placeholder so the section keeps its height.
                  ['Database', 'Redis', 'Email Ingestion'].map((label) => (
                    <SystemHealthCard
                      key={label}
                      label={label}
                      status="loading"
                      subtitle="Checking…"
                    />
                  ))
                )}
              </div>
            </div>

            {isPlatformAdmin ? (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                {platformStatsTiles.map((tile) => (
                  <div
                    key={tile.label}
                    className="rounded-lg bg-card p-4 text-center shadow-[0_1px_2px_rgba(0,0,0,0.05)]"
                  >
                    <p className="text-xs text-muted-foreground">{tile.label}</p>
                    <p className="text-2xl font-bold mt-1">{tile.value}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3 mb-4">
                {adminStatsTiles.map((tile) => (
                  <button
                    key={tile.key}
                    type="button"
                    onClick={() => handleAdminTileClick(tile.key)}
                    onKeyDown={(event) => handleAdminTileKeyDown(event, tile.key)}
                    aria-label={`${tile.label}: ${tile.value}. ${getAdminTileActionLabel(tile.key)}`}
                    className="rounded-lg bg-card p-4 text-center shadow-[0_1px_2px_rgba(0,0,0,0.05)] transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
                  >
                    <p className="text-xs text-muted-foreground">{tile.label}</p>
                    <p className="text-2xl font-bold mt-1">{tile.value}</p>
                  </button>
                ))}
              </div>
            )}

            <div className="rounded-lg bg-card p-5 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
              <button
                type="button"
                onClick={() => setShowRecentActivity((v) => !v)}
                className="flex w-full items-center justify-between gap-3"
              >
                <h2 className="text-lg font-semibold">
                  {isPlatformAdmin ? 'Recent Platform Activity' : 'Recent Org Activity'}
                </h2>
                <div className="flex items-center gap-2">
                  <p className="text-xs text-muted-foreground">{recentActivity.length || 0} items</p>
                  <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${showRecentActivity ? 'rotate-180' : ''}`} />
                </div>
              </button>

              {showRecentActivity && (
                <div className="mt-4">
                  {recentActivityLoading ? (
                    <p className="text-sm text-muted-foreground">Loading recent activity…</p>
                  ) : recentActivity.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No recent activity yet.</p>
                  ) : (
                    <div className="space-y-3">
                      {recentActivity.map((item: DashboardRecentActivityItem) => (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => navigate(buildRouteWithParams(item.route, item.route_params))}
                          className="w-full rounded-md border px-4 py-3 text-left transition-colors hover:bg-muted/30"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-foreground">{item.summary}</p>
                              <p className="mt-1 text-xs text-muted-foreground">
                                {format(parseISO(item.created_at), 'MMM d, yyyy • h:mm a')}
                              </p>
                            </div>
                            <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${getActivitySeverityClasses(item.severity)}`}>
                              {getActivitySeverityLabel(item.severity)}
                            </span>
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        )}

        {/* Manager Team-tab layout. Lives outside the personal-time
            block so it isn't gated by `showPersonalTimeView`. */}
        {showManagerTeamSection && (
          <>
            {/* Hero: conversation paragraph + actions. Generated
                client-side from the overview; no separate priorities
                card any more — the paragraph carries that signal. */}
            <ManagerConversation
              overview={managerOverview}
              ingestionEnabled={ingestionEnabled && canReview}
              pendingIngestionCount={pendingReviewCount}
            />

            {/* Glance tiles: 5 numbers across all the dimensions a
                manager scans in their first minute. */}
            <ManagerGlanceTiles
              overview={managerOverview}
              ingestionEnabled={ingestionEnabled && canReview}
              pendingIngestionCount={pendingReviewCount}
              projectAlertCount={(managerProjectHealth?.rows ?? []).filter((r) => r.health === 'needs-attention' || r.health === 'at-risk').length}
            />

            {/* Project health: the team's projects with budget + time
                signals. Replaces the bar chart + donut for managers. */}
            <div className="rounded-lg border bg-card p-5 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-foreground">Project health</h2>
                <span className="text-xs text-muted-foreground">Sorted by attention needed</span>
              </div>
              <ProjectHealthTable
                rows={managerProjectHealth?.rows ?? []}
                isLoading={managerProjectHealthLoading}
              />
            </div>

            {/* Roster as a collapsible card. Default: collapsed with
                summary pills visible; click to drill into per-person
                detail. */}
            <ManagerTeamRosterCard
              overview={managerOverview}
              loading={managerOverviewLoading}
              selectedUserId={selectedUserId}
              onSelect={(userId) => setSelectedUserId(userId)}
            />
          </>
        )}

        {showPersonalTimeView && (
          <>
        {selectedEmployeeName && (
          <div className="mb-4 rounded-md border bg-muted/30 px-4 py-3 text-base font-bold text-foreground md:text-lg">
            Viewing data for: {selectedEmployeeName}
          </div>
        )}

        <div className="mb-4 rounded-lg border bg-card p-6">
          <div className="mb-4 flex items-center justify-between gap-3 flex-wrap rounded-md border border-primary/20 bg-primary/5 px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-primary">Weekly View</span>
              <span className="text-sm font-medium text-foreground">{weekRange.label}</span>
            </div>
            <p className="text-xs text-muted-foreground">
              {format(parseISO(weekRange.startDate), 'EEE, MMM d')} to {format(parseISO(weekRange.endDate), 'EEE, MMM d')}
            </p>
          </div>

          <div className={`grid gap-4 ${showProjectClientWidgets ? 'grid-cols-1 md:grid-cols-3' : 'grid-cols-1'}`}>
            <div className="text-center">
            <p className="text-sm text-muted-foreground mb-1">Total time</p>
            <p className="text-3xl font-bold">{formatHours(totalHours)}</p>
            {totalHours > 0 && (
              <div className="mt-1 flex justify-center gap-3 text-xs text-muted-foreground">
                <span className="text-green-700 font-medium">{formatHours(billableHours)} billable</span>
                {nonBillableHours > 0 && (
                  <span className="text-orange-600 font-medium">{formatHours(nonBillableHours)} non-billable</span>
                )}
              </div>
            )}
            </div>
            {showProjectClientWidgets && (
              <>
                <div className="text-center">
                  <p className="text-sm text-muted-foreground mb-1">Top Project</p>
                  <p className="text-2xl font-semibold truncate">{analytics?.top_project_name ?? '---'}</p>
                </div>
                <div className="text-center">
                  <p className="text-sm text-muted-foreground mb-1">Top Client</p>
                  <p className="text-2xl font-semibold truncate">{analytics?.top_client_name ?? '---'}</p>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px] gap-4 mb-4">
          <div className="rounded-lg border bg-card p-6 overflow-x-auto">
            <div className="min-w-[720px]">
              <DashboardBarChart data={dailyBreakdown} projectColorMap={projectColorMap} onSelectSegment={setSelectedBarSegment} />
            </div>
          </div>

          <div className="rounded-lg border bg-card p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Most tracked activities</h2>
              <span className="text-sm text-muted-foreground">Top 10</span>
            </div>
            <div className="space-y-3">
              {topActivities.length === 0 ? (
                <p className="text-sm text-muted-foreground">No activity for this range.</p>
              ) : (
                topActivities.map((activity: DashboardActivity, index: number) => (
                  <div key={`${activity.project_name}-${activity.description}-${index}`} className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm truncate">{activity.description || '(no description)'}</p>
                      {showProjectClientWidgets && (
                        <p className="text-xs text-muted-foreground truncate">• {activity.project_name}</p>
                      )}
                    </div>
                    <span className="text-sm font-medium whitespace-nowrap">{formatHours(toNumber(activity.hours))}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {showProjectClientWidgets && (
          <div className="rounded-lg border bg-card p-6">
            <div className="flex flex-col xl:flex-row items-start xl:items-center gap-8">
              <DashboardDonutChart data={projectBreakdown} totalHours={totalHours} />

              <div className="flex-1 w-full space-y-4">
                {projectBreakdown.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No project data for this range.</p>
                ) : (
                  projectBreakdown.map((project: DashboardProjectBreakdown, index: number) => (
                    <div key={project.project_id} className="flex items-center gap-3">
                      <div
                        className="h-3 w-3 rounded-full shrink-0"
                        style={{ backgroundColor: projectColorMap[project.project_id] ?? PROJECT_COLORS[index % PROJECT_COLORS.length] }}
                      />
                      <span className="text-sm flex-1 truncate">{project.project_name}</span>
                      <span className="text-sm text-muted-foreground whitespace-nowrap">{formatHours(toNumber(project.hours))}</span>
                      <div className="w-40 h-4 rounded-sm bg-muted overflow-hidden">
                        <div
                          className="h-full"
                          style={{
                            width: `${Math.max(project.percentage, 4)}%`,
                            backgroundColor: projectColorMap[project.project_id] ?? PROJECT_COLORS[index % PROJECT_COLORS.length],
                          }}
                        />
                      </div>
                      <span className="text-sm text-muted-foreground w-16 text-right">{project.percentage.toFixed(2)}%</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
          </>
        )}

        {showPersonalTimeView && selectedBarSegment && (
          <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
            <div className="w-full max-w-lg rounded-lg border bg-card p-5 shadow-2xl">
              <div className="flex items-start justify-between gap-4 mb-4">
                <div>
                  <h3 className="text-lg font-semibold">Entry details</h3>
                  <p className="text-sm text-muted-foreground">{format(parseISO(selectedBarSegment.entryDate), 'MMM d, yyyy')}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedBarSegment(null)}
                  className="px-2 py-1 text-sm rounded border hover:bg-muted"
                >
                  Close
                </button>
              </div>
              <div className="space-y-2 text-sm">
                {showProjectClientWidgets && (
                  <>
                    <p><span className="text-muted-foreground">Project:</span> {selectedBarSegment.projectName}</p>
                    <p><span className="text-muted-foreground">Client:</span> {selectedBarSegment.clientName}</p>
                  </>
                )}
                <p><span className="text-muted-foreground">Hours:</span> {formatHours(selectedBarSegment.totalHours)}</p>
              </div>
              <div className="mt-4 border-t pt-3 space-y-2 max-h-64 overflow-y-auto">
                {selectedBarSegment.entries.map((entry) => (
                  <button
                    type="button"
                    key={entry.entry_id}
                    onClick={() => {
                      const mode = entry.status === 'DRAFT' ? 'edit' : 'view';
                      navigate(`/my-time?entryId=${entry.entry_id}&date=${entry.entry_date}&mode=${mode}`);
                      setSelectedBarSegment(null);
                    }}
                    className="w-full text-left rounded border p-2 text-sm hover:bg-muted/40"
                  >
                    <p><span className="text-muted-foreground">Entry #:</span> {entry.entry_id}</p>
                    <p><span className="text-muted-foreground">Status:</span> {entry.status}</p>
                    <p><span className="text-muted-foreground">Hours:</span> {formatHours(toNumber(entry.hours))}</p>
                    <p><span className="text-muted-foreground">Description:</span> {entry.description}</p>
                  </button>
                ))}
              </div>
              <p className="mt-3 text-xs text-muted-foreground">Click an entry to open it in My Time (draft opens in edit mode).</p>
            </div>
          </div>
        )}

        {showAdminStatsView && isNotificationsModalOpen && (
          <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
            <div
              role="dialog"
              aria-modal="true"
              aria-labelledby="dashboard-notifications-title"
              className="w-full max-w-2xl rounded-lg border bg-card p-5 shadow-2xl max-h-[80vh] overflow-y-auto"
            >
              <div className="flex items-center justify-between gap-3 mb-4">
                <h3 id="dashboard-notifications-title" className="text-lg font-semibold">Notifications</h3>
                <button
                  type="button"
                  onClick={() => setIsNotificationsModalOpen(false)}
                  aria-label="Close notifications dialog"
                  className="px-3 py-1.5 text-sm rounded border hover:bg-muted"
                >
                  Close
                </button>
              </div>

              {(notificationItems as NotificationItem[]).length === 0 ? (
                <p className="text-sm text-muted-foreground">No unread notifications.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {(notificationItems as NotificationItem[]).map((notification) => (
                    <li key={notification.id} className="rounded-md border p-3">
                      <p className="font-medium">{notification.title}</p>
                      <p className="text-muted-foreground text-xs mt-1">{notification.message}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
