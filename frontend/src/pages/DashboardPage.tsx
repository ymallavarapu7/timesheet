import React, { useEffect, useMemo, useRef, useState } from 'react';
import { addWeeks, endOfWeek, format, isThisWeek, isToday, parseISO, startOfWeek } from 'date-fns';
import { Calendar, Check, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Loading, Error, ChangePasswordModal, AdminActionQueue, DashboardGreeting, SystemHealthCard, WeeklyRoster, ManagerConversation, ManagerGlanceTiles, ProjectHealthTable, QuickLogButton } from '@/components';
import type { SystemHealthStatus } from '@/components/SystemHealthCard';
import {
  TotalTimeWidget,
  TodayTimeWidget,
  UtilizationWidget,
  TopProjectWidget,
  DailyBarChartWidget,
  TopActivitiesWidget,
  ProjectsBreakdownWidget,
  TimeOffBalanceWidget,
  ProductivityWidget,
  OvertimeWidget,
  AddWidgetCard,
  WidgetPickerPanel,
} from '@/components/dashboard';
import { useDashboardPrefs } from '@/hooks/useDashboardPrefs';
import { WIDGET_REGISTRY, type WidgetKey } from '@/hooks/useWidgetPreferences';
import { WidgetWrapper } from '@/components/dashboard/WidgetWrapper';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import { SortableContext, rectSortingStrategy } from '@dnd-kit/sortable';
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
  useTimeEntries,
  useWeekStartsOn,
  useAdminSystemHealth,
  useManagerTeamOverview,
  useManagerProjectHealth,
} from '@/hooks';
import type { DashboardActivity, DashboardDayBreakdown, DashboardProjectBreakdown, DashboardRecentActivityItem, NotificationItem, Project, Tenant, User } from '@/types';

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

type AdminStatsTileKey = 'people' | 'clients' | 'active-projects' | 'pending-invites' | 'notifications';

const getAdminTileActionLabel = (tileKey: AdminStatsTileKey) => {
  if (tileKey === 'people') return 'Opens User Management.';
  if (tileKey === 'clients') return 'Opens Client Management.';
  if (tileKey === 'active-projects') return 'Opens Client Management in Projects view filtered to Active projects.';
  if (tileKey === 'pending-invites') return 'Opens User Management filtered to unverified accounts.';
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

const EmployeeWidgetGrid: React.FC<{
  weekRange: { startDate: string; endDate: string; label: string };
  totalHours: number;
  billableHours: number;
  dailyBreakdown: DashboardDayBreakdown[];
  topActivities: DashboardActivity[];
  projectBreakdown: DashboardProjectBreakdown[];
  projects: Project[];
  topProjectName: string | null;
  topProjectHours: number;
  selectedEmployeeName: string | null;
}> = ({
  totalHours,
  billableHours,
  dailyBreakdown,
  topActivities,
  projectBreakdown,
  topProjectName,
  topProjectHours,
  selectedEmployeeName,
}) => {
  const { prefs, toggleWidget, setOrder, cycleSize } = useDashboardPrefs();
  const [pickerOpen, setPickerOpen] = useState(false);

  const [screenWidth, setScreenWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 1200);
  useEffect(() => {
    const handler = () => setScreenWidth(window.innerWidth);
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);
  const isMobile = screenWidth < 768;
  const isTablet = screenWidth >= 768 && screenWidth < 1024;
  const gridCols = isMobile ? 1 : isTablet ? 6 : 12;

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
  );

  const todayHours = useMemo(() => {
    const todayEntry = dailyBreakdown.find((d) => isToday(parseISO(d.entry_date)));
    return todayEntry ? toNumber(todayEntry.hours) : 0;
  }, [dailyBreakdown]);

  const visibleKeys = useMemo(() => {
    return prefs.order.filter((key) => prefs.visible[key]);
  }, [prefs.order, prefs.visible]);

  const getEffectiveSpan = (key: WidgetKey): number => {
    if (isMobile) return 1;
    const rawSpan = prefs.sizes[key];
    if (isTablet) return Math.max(2, Math.round(rawSpan / 2));
    return rawSpan;
  };

  const renderWidget = (key: WidgetKey) => {
    switch (key) {
      case 'total':
        return (
          <TotalTimeWidget
            totalHours={totalHours}
            onRemove={() => toggleWidget('total')}
          />
        );
      case 'today':
        return (
          <TodayTimeWidget
            todayHours={todayHours}
            onRemove={() => toggleWidget('today')}
          />
        );
      case 'util':
        return (
          <UtilizationWidget
            totalHours={totalHours}
            onRemove={() => toggleWidget('util')}
          />
        );
      case 'productivity':
        return (
          <ProductivityWidget
            totalHours={totalHours}
            billableHours={billableHours}
            onRemove={() => toggleWidget('productivity')}
          />
        );
      case 'overtime':
        return (
          <OvertimeWidget
            totalHours={totalHours}
            targetHours={40}
            onRemove={() => toggleWidget('overtime')}
          />
        );
      case 'tproject':
        return (
          <TopProjectWidget
            projectName={topProjectName}
            hours={topProjectHours}
            totalHours={totalHours}
            onRemove={() => toggleWidget('tproject')}
          />
        );
      case 'barchart':
        return (
          <DailyBarChartWidget
            data={dailyBreakdown}
            onRemove={() => toggleWidget('barchart')}
          />
        );
      case 'activity':
        return (
          <TopActivitiesWidget
            activities={topActivities}
            totalHours={totalHours}
            onRemove={() => toggleWidget('activity')}
          />
        );
      case 'projects':
        return (
          <ProjectsBreakdownWidget
            projects={projectBreakdown}
            onRemove={() => toggleWidget('projects')}
          />
        );
      case 'timeoff':
        return (
          <TimeOffBalanceWidget
            annual={12}
            sick={6}
            wfh={24}
            onRemove={() => toggleWidget('timeoff')}
          />
        );
      default:
        return null;
    }
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (over && active.id !== over.id) {
      const oldIdx = prefs.order.indexOf(active.id as WidgetKey);
      const newIdx = prefs.order.indexOf(over.id as WidgetKey);
      if (oldIdx !== -1 && newIdx !== -1) {
        const newOrder = [...prefs.order];
        newOrder.splice(oldIdx, 1);
        newOrder.splice(newIdx, 0, active.id as WidgetKey);
        setOrder(newOrder);
      }
    }
  };

  return (
    <>
      {selectedEmployeeName && (
        <div className="mb-4 rounded-lg border bg-muted/30 px-4 py-3 text-base font-bold text-foreground md:text-lg">
          Viewing data for: {selectedEmployeeName}
        </div>
      )}

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext items={visibleKeys} strategy={rectSortingStrategy}>
          <div
            className="grid gap-4 grid-flow-dense"
            style={{
              gridTemplateColumns: isMobile ? '1fr' : `repeat(${gridCols}, 1fr)`,
            }}
          >
            {visibleKeys.map((key) => (
              <WidgetWrapper
                key={key}
                id={key}
                span={getEffectiveSpan(key)}
                title={WIDGET_REGISTRY.find((w) => w.key === key)?.label}
                onResize={() => cycleSize(key)}
                isMobile={isMobile}
              >
                {renderWidget(key)}
              </WidgetWrapper>
            ))}

            <div style={{ gridColumn: isMobile ? '1 / -1' : 'span 3' }}>
              <AddWidgetCard onClick={() => setPickerOpen(true)} />
            </div>
          </div>
        </SortableContext>
      </DndContext>

      <WidgetPickerPanel
        isOpen={pickerOpen}
        onClose={() => setPickerOpen(false)}
        state={prefs.visible}
        onToggle={toggleWidget}
      />
    </>
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
  const [adminDashboardView, setAdminDashboardView] = useState<'stats' | 'my-time'>('stats');
  const [managerDashboardView, setManagerDashboardView] = useState<'team' | 'my-time'>('team');
  const [isNotificationsModalOpen, setIsNotificationsModalOpen] = useState(false);
  const [isPasswordChangeModalOpen, setIsPasswordChangeModalOpen] = useState(false);
  const [showWeekPicker, setShowWeekPicker] = useState(false);
  // D7: popover modes are 'presets' (four offsets), 'custom' (range
  // calendar). Custom flips the source of truth from weekOffset to
  // customRange so we can express single-day or arbitrary spans.
  const [weekPickerMode, setWeekPickerMode] = useState<'presets' | 'custom'>('presets');
  // When non-null, this overrides the weekOffset-derived range. Set
  // by the custom calendar's two-click selection. Cleared whenever
  // the user picks a preset.
  const [customRange, setCustomRange] = useState<{ start: Date; end: Date } | null>(null);
  // Two-click selection state inside the custom calendar: first click
  // sets pendingStart and shows a hover preview; second click commits
  // the range. Reset on popover close.
  const [pendingRangeStart, setPendingRangeStart] = useState<Date | null>(null);
  // Recent Activity collapsed by default; a "N new since last login"
  // chip on the header tells the admin if anything's worth opening.
  const [showRecentActivity, setShowRecentActivity] = useState(false);
  const [recentActivityExpanded, setRecentActivityExpanded] = useState(false);
  const previousLoginAt = useMemo(() => {
    const stored = sessionStorage.getItem('previous_last_login_at');
    if (!stored) return null;
    const ts = Date.parse(stored);
    return Number.isFinite(ts) ? ts : null;
  }, []);
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

  useEffect(() => {
    if (!showWeekPicker) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setShowWeekPicker(false); setWeekPickerMode('presets'); }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [showWeekPicker]);

  const isManagerView = user?.role === 'MANAGER' || user?.role === 'SENIOR_MANAGER';
  const isPlatformAdmin = user?.role === 'PLATFORM_ADMIN';
  const isAdminView = user?.role === 'ADMIN';
  const showProjectClientWidgets = !isAdminView && !isPlatformAdmin;
  const showAdminStatsView = isPlatformAdmin || (isAdminView && adminDashboardView === 'stats');
  // Personal-time view: default for plain users; managers/admins must opt in.
  const showPersonalTimeView = (
    (!isAdminView && !isPlatformAdmin && !isManagerView)
    || (isAdminView && adminDashboardView === 'my-time')
    || (isManagerView && managerDashboardView === 'my-time')
  );
  const showManagerTeamSection = isManagerView && managerDashboardView === 'team';

  const weekRange = useMemo(() => {
    // Custom range wins over the preset offset. Used when the admin
    // / employee picks an arbitrary span (single day, mid-week to
    // mid-week, etc.) from the custom calendar.
    if (customRange) {
      const start = customRange.start;
      const end = customRange.end;
      const sameDay = format(start, 'yyyy-MM-dd') === format(end, 'yyyy-MM-dd');
      return {
        startDate: format(start, 'yyyy-MM-dd'),
        endDate: format(end, 'yyyy-MM-dd'),
        label: sameDay
          ? format(start, 'MMM d')
          : `${format(start, 'MMM d')} - ${format(end, 'MMM d')}`,
      };
    }

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
  }, [isManagerView, weekOffset, customRange, weekStartsOn]);

  const { data: projects = [], isLoading: projectsLoading } = useProjects({ active_only: true });
  const { data: teamEmployees = [], isLoading: teamLoading } = useTeamEmployees();
  const { data: teamDailyOverview, isLoading: teamDailyLoading } = useTeamDailyOverview();
  const { data: users = [], isLoading: usersLoading, error: usersError } = useUsers(isAdminView);
  const { data: tenants = [], isLoading: tenantsLoading, error: tenantsError } = useTenants(isPlatformAdmin);
  const { data: clients = [], isLoading: clientsLoading, error: clientsError } = useClients();
  const { data: notificationsSummary, isLoading: notificationsLoading, error: notificationsError, isFetching: notificationsFetching, isError: notificationsIsError } = useNotifications();
  const canReview = useCanReview();
  const ingestionEnabled = useIngestionEnabled();
  // Admin dashboard no longer surfaces review queue size, so we don't
  // fetch it when the user is an admin. Managers and reviewers still
  // need it for their own tiles.
  const { data: pendingTimesheets = [] } = useIngestionTimesheets(
    { status_filter: 'pending', limit: 200 },
    canReview && ingestionEnabled && !isAdminView,
  );
  const pendingReviewCount = pendingTimesheets.length;
  const { data: recentActivity = [], isLoading: recentActivityLoading, error: recentActivityError } = useDashboardRecentActivity({ limit: 12 }, showAdminStatsView);
  // Live infra health for the admin dashboard. Polls every 30s while
  // the admin stats view is mounted; idle otherwise.
  const { data: systemHealth, isLoading: systemHealthLoading } = useAdminSystemHealth(showAdminStatsView);
  // Draft count for the admin's own time entries this week. Surfaced
  // as a chip on the Weekly View card in the My Time view. Endpoint
  // scopes to the current user, so no user_id param needed.
  const { data: adminDraftEntries = [] } = useTimeEntries(
    { start_date: weekRange.startDate, end_date: weekRange.endDate, status: 'draft', limit: 200 },
    isAdminView && !isPlatformAdmin && adminDashboardView === 'my-time',
  );
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

  // Pending invitations: active accounts whose email is unverified.
  // Same definition as the Action Queue's stale-invitation rule, just
  // without the >7d cutoff (this tile is a glance count; the Action
  // Queue surfaces only the ones old enough to act on).
  const pendingInvitesCount = allUsers.filter(
    (u) => u.is_active && !u.email_verified,
  ).length;

  const adminStatsTiles: {
    key: AdminStatsTileKey;
    label: string;
    value: number;
    hint?: string;
  }[] = [
    {
      key: 'people',
      label: 'People',
      value: activeUsersCount,
      // Compact role breakdown sits below the headline number so the
      // tile carries the same information as the four old tiles in
      // one card.
      hint: `${employeesCount} emp · ${managersCount} mgr · ${adminsCount} adm`,
    },
    { key: 'clients', label: 'Clients', value: allClients.length },
    { key: 'active-projects', label: 'Active Projects', value: activeProjectCount },
    { key: 'pending-invites', label: 'Pending Invites', value: pendingInvitesCount },
    { key: 'notifications', label: 'Notifications', value: totalNotifications },
  ];

  const platformStatsTiles = [
    { label: 'Total Tenants', value: allTenants.length },
    { label: 'Active', value: allTenants.filter((t) => t.status === 'active').length },
    { label: 'Inactive', value: allTenants.filter((t) => t.status === 'inactive').length },
    { label: 'Suspended', value: allTenants.filter((t) => t.status === 'suspended').length },
  ];

  const handleAdminTileClick = (tileKey: AdminStatsTileKey) => {
    if (tileKey === 'people') {
      navigate('/user-management?status=ACTIVE');
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
    if (tileKey === 'pending-invites') {
      navigate('/user-management?verified=NO');
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
        {/* Shared greeting; role-specific content renders below. */}
        <div className="flex items-end justify-between gap-4 mb-6 flex-wrap">
          <div className="min-w-0">
            <DashboardGreeting userFullName={user?.full_name} />
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Universal quick-log: every user can log time from any
                dashboard view. Sits as a popover-from-button so it
                doesn't compete with the dashboard's read content. */}
            <QuickLogButton className="relative" />
            {isManagerView && (
              <div className="flex items-center rounded-lg border bg-card overflow-hidden">
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
              <div className="flex items-center rounded-lg border bg-card overflow-hidden">
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
                  <div className="fixed inset-0 z-40" onClick={() => { setShowWeekPicker(false); setWeekPickerMode('presets'); }} />
                  <div className="absolute top-full right-0 z-50 mt-1 bg-card border border-border rounded-xl shadow-lg p-2 select-none" style={{ minWidth: 220 }} onClick={(e) => e.stopPropagation()}>
                    {/* Compact week picker: presets + custom calendar. */}
                    {weekPickerMode === 'presets' ? (
                      <ul className="space-y-1">
                        {[0, -1, -2, -3].map((offset) => {
                          const label = offset === 0
                            ? 'This week'
                            : offset === -1
                              ? 'Last week'
                              : `${Math.abs(offset)} weeks ago`;
                          const active = !customRange && weekOffset === offset;
                          return (
                            <li key={offset}>
                              <button
                                type="button"
                                onClick={() => {
                                  setCustomRange(null);
                                  setWeekOffset(offset);
                                  setShowWeekPicker(false);
                                }}
                                className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm transition ${active ? 'bg-primary/10 text-primary font-semibold' : 'hover:bg-muted'}`}
                              >
                                <span>{label}</span>
                                {active && <Check className="h-3.5 w-3.5" />}
                              </button>
                            </li>
                          );
                        })}
                        <li className="border-t border-border pt-1 mt-1">
                          <button
                            type="button"
                            onClick={() => {
                              setWeekPickerMode('custom');
                              setPendingRangeStart(null);
                            }}
                            className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm transition ${customRange ? 'bg-primary/10 text-primary font-semibold' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
                          >
                            <span>Custom range…</span>
                            <ChevronRight className="h-3.5 w-3.5" />
                          </button>
                        </li>
                      </ul>
                    ) : (
                      // Two-click range select; same day twice = single-day range.
                      <div style={{ minWidth: 280 }}>
                        <div className="flex items-center justify-between mb-2">
                          <button type="button" className="p-1 rounded hover:bg-muted" onClick={() => { setWeekPickerMode('presets'); setPendingRangeStart(null); }} aria-label="Back to presets">
                            <ChevronLeft className="h-4 w-4" />
                          </button>
                          <span className="text-sm font-semibold">{format(pickerMonth, 'MMMM yyyy')}</span>
                          <div className="flex items-center">
                            <button type="button" className="p-1 rounded hover:bg-muted" onClick={() => setPickerMonth((m) => { const d = new Date(m); d.setMonth(d.getMonth() - 1); return d; })} aria-label="Previous month">
                              <ChevronLeft className="h-4 w-4" />
                            </button>
                            <button type="button" className="p-1 rounded hover:bg-muted" onClick={() => setPickerMonth((m) => { const d = new Date(m); d.setMonth(d.getMonth() + 1); return d; })} aria-label="Next month">
                              <ChevronRight className="h-4 w-4" />
                            </button>
                          </div>
                        </div>
                        <p className="px-1 pb-2 text-xs text-muted-foreground">
                          {pendingRangeStart
                            ? `Start: ${format(pendingRangeStart, 'MMM d')}. Pick the end date.`
                            : 'Pick a start date.'}
                        </p>
                        <div className="grid grid-cols-7 mb-1">
                          {['Su','Mo','Tu','We','Th','Fr','Sa'].map((d) => (
                            <div key={d} className="text-center text-xs font-medium text-muted-foreground py-1">{d}</div>
                          ))}
                        </div>
                        {(() => {
                          const monthStart = new Date(pickerMonth.getFullYear(), pickerMonth.getMonth(), 1);
                          const gridStart = startOfWeek(monthStart, { weekStartsOn });
                          const selectedStart = customRange?.start ?? null;
                          const selectedEnd = customRange?.end ?? null;
                          const days: React.ReactNode[] = [];
                          for (let i = 0; i < 42; i++) {
                            const day = new Date(gridStart);
                            day.setDate(gridStart.getDate() + i);
                            const isCurrentMonth = day.getMonth() === pickerMonth.getMonth();
                            const dayKey = format(day, 'yyyy-MM-dd');
                            const inCommittedRange = selectedStart && selectedEnd
                              && day >= selectedStart && day <= selectedEnd;
                            const isPendingStart = pendingRangeStart
                              && format(pendingRangeStart, 'yyyy-MM-dd') === dayKey;
                            const isCommittedStart = selectedStart
                              && format(selectedStart, 'yyyy-MM-dd') === dayKey;
                            const isCommittedEnd = selectedEnd
                              && format(selectedEnd, 'yyyy-MM-dd') === dayKey;
                            const highlighted = isPendingStart || inCommittedRange;
                            const cls = highlighted
                              ? `bg-primary/15 text-primary ${isCommittedStart || isCommittedEnd || isPendingStart ? 'font-semibold ring-1 ring-primary' : ''}`
                              : `hover:bg-muted ${!isCurrentMonth ? 'text-muted-foreground/50' : ''}`;
                            days.push(
                              <button
                                key={i}
                                type="button"
                                onClick={() => {
                                  const clicked = new Date(day.getFullYear(), day.getMonth(), day.getDate());
                                  if (!pendingRangeStart) {
                                    // First click: stage the start.
                                    setPendingRangeStart(clicked);
                                    return;
                                  }
                                  // Second click: commit. Swap if the
                                  // user picked an end before the
                                  // start so the range is always
                                  // ordered.
                                  let start = pendingRangeStart;
                                  let end = clicked;
                                  if (end < start) {
                                    [start, end] = [end, start];
                                  }
                                  setCustomRange({ start, end });
                                  setPendingRangeStart(null);
                                  setShowWeekPicker(false);
                                  setWeekPickerMode('presets');
                                }}
                                className={`text-center text-xs py-1.5 rounded transition ${cls}`}
                                title={format(day, 'MMM d, yyyy')}
                              >
                                {day.getDate()}
                              </button>
                            );
                          }
                          return <div className="grid grid-cols-7 gap-y-0.5">{days}</div>;
                        })()}
                      </div>
                    )}
                  </div>
                </>
              )}
              <div className="flex items-center rounded-lg border bg-card overflow-hidden">
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
            {/* 1. Action Queue: what does the org need from me right now?
                Top of the page so urgent items aren't pushed below the
                fold by infra checks that are usually green. */}
            {isAdminView && !isPlatformAdmin && (
              <AdminActionQueue
                users={allUsers}
                notifications={notificationItems as NotificationItem[]}
                recentActivity={recentActivity}
                recentActivityLoading={recentActivityLoading}
                currentUserId={user?.id ?? null}
                onOpenNotifications={() => setIsNotificationsModalOpen(true)}
              />
            )}

            {/* 2. Tile row: primary navigation. Most admin clicks land on
                People / Clients / Projects management; keeping these
                above the fold means fewer scrolls per session. */}
            {isPlatformAdmin ? (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                {platformStatsTiles.map((tile) => (
                  <div
                    key={tile.label}
                    className="rounded-lg bg-card p-3 text-center shadow-[0_1px_2px_rgba(0,0,0,0.05)]"
                  >
                    <p className="text-xs text-muted-foreground">{tile.label}</p>
                    <p className="text-2xl font-bold mt-1">{tile.value}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3 mb-4">
                {adminStatsTiles.map((tile) => (
                  <button
                    key={tile.key}
                    type="button"
                    onClick={() => handleAdminTileClick(tile.key)}
                    onKeyDown={(event) => handleAdminTileKeyDown(event, tile.key)}
                    aria-label={`${tile.label}: ${tile.value}${tile.hint ? `. ${tile.hint}` : ''}. ${getAdminTileActionLabel(tile.key)}`}
                    className="rounded-lg bg-card p-3 text-center shadow-[0_1px_2px_rgba(0,0,0,0.05)] transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
                  >
                    <p className="text-xs text-muted-foreground">{tile.label}</p>
                    <p className="text-2xl font-bold mt-1 leading-tight">{tile.value}</p>
                    {tile.hint && (
                      <p className="mt-1 text-xs text-muted-foreground">{tile.hint}</p>
                    )}
                  </button>
                ))}
              </div>
            )}

            {/* Recent Activity collapsed by default; "N new" chip on header. */}
            {(() => {
              const newSinceLogin = previousLoginAt == null
                ? 0
                : recentActivity.filter((it) => {
                    const ts = Date.parse(it.created_at);
                    return Number.isFinite(ts) && ts > previousLoginAt;
                  }).length;
              return (
            <div className="rounded-lg bg-card p-4 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
              <button
                type="button"
                onClick={() => setShowRecentActivity((v) => !v)}
                className="flex w-full items-center justify-between gap-3"
              >
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-semibold">
                    {isPlatformAdmin ? 'Recent Platform Activity' : 'Recent Org Activity'}
                  </h2>
                  {newSinceLogin > 0 && (
                    <span className="inline-flex items-center rounded-full border border-sky-400/40 bg-sky-500/10 px-2 py-0.5 text-[11px] font-semibold text-sky-700 dark:text-sky-300">
                      {newSinceLogin} new since last login
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <p className="text-xs text-muted-foreground">{recentActivity.length || 0} items</p>
                  <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${showRecentActivity ? 'rotate-180' : ''}`} />
                </div>
              </button>

              {showRecentActivity && (
                <div className="mt-3">
                  {recentActivityLoading ? (
                    <p className="text-sm text-muted-foreground">Loading recent activity…</p>
                  ) : recentActivity.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No recent activity yet.</p>
                  ) : (() => {
                    const visibleActivity = recentActivityExpanded
                      ? recentActivity
                      : recentActivity.slice(0, 5);
                    const hiddenCount = recentActivity.length - visibleActivity.length;
                    return (
                      <>
                        <div className="space-y-2">
                          {visibleActivity.map((item: DashboardRecentActivityItem) => {
                            const ts = Date.parse(item.created_at);
                            const isNew = previousLoginAt != null && Number.isFinite(ts) && ts > previousLoginAt;
                            return (
                            <button
                              key={item.id}
                              type="button"
                              onClick={() => navigate(buildRouteWithParams(item.route, item.route_params))}
                              className={`w-full rounded-md border px-3 py-2 text-left transition-colors hover:bg-muted/30 ${
                                isNew
                                  ? 'border-sky-400/40 bg-sky-500/[0.07]'
                                  : ''
                              }`}
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <p className="text-sm font-medium text-foreground">
                                    {isNew && (
                                      <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-sky-500 align-middle" aria-label="New" />
                                    )}
                                    {item.summary}
                                  </p>
                                  <p className="mt-0.5 text-xs text-muted-foreground">
                                    {format(parseISO(item.created_at), 'MMM d, yyyy • h:mm a')}
                                  </p>
                                </div>
                                <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${getActivitySeverityClasses(item.severity)}`}>
                                  {getActivitySeverityLabel(item.severity)}
                                </span>
                              </div>
                            </button>
                            );
                          })}
                        </div>
                        {hiddenCount > 0 && (
                          <button
                            type="button"
                            onClick={() => setRecentActivityExpanded(true)}
                            className="mt-2 text-xs font-medium text-primary hover:underline"
                          >
                            Show {hiddenCount} more
                          </button>
                        )}
                        {recentActivityExpanded && recentActivity.length > 5 && (
                          <button
                            type="button"
                            onClick={() => setRecentActivityExpanded(false)}
                            className="mt-2 text-xs font-medium text-muted-foreground hover:underline"
                          >
                            Show less
                          </button>
                        )}
                      </>
                    );
                  })()}
                </div>
              )}
            </div>
              );
            })()}

            {/* 4. System Health: demoted to bottom. Infra is healthy 99%
                of the time; when it's not, the issue surfaces in the
                Action Queue at the top. This card is a confirmation, not
                a primary signal. */}
            <div className="rounded-lg bg-card p-4 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-base font-semibold">System Health</h2>
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
          <EmployeeWidgetGrid
            weekRange={weekRange}
            totalHours={totalHours}
            billableHours={billableHours}
            dailyBreakdown={dailyBreakdown}
            topActivities={topActivities}
            projectBreakdown={projectBreakdown}
            projects={projectOptions}
            topProjectName={analytics?.top_project_name ?? null}
            topProjectHours={toNumber(analytics?.top_project_hours ?? 0)}
            selectedEmployeeName={selectedEmployeeName}
          />
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
