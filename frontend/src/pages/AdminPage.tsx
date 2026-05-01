import React, { useState } from 'react';
import { format, startOfMonth, endOfMonth } from 'date-fns';
import { PlusCircle, Pencil, Trash2, ShieldCheck, UserCircle, X, Clock, Paperclip, Building2, MoreVertical, MailCheck } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { Loading, Error, OrganizationalChart, SearchInput } from '@/components';
import { BulkSelectBar } from '@/components/ui/BulkSelectBar';
import { cn } from '@/lib/utils';
import { useUsers, useCreateUser, useUpdateUser, useDeleteUser, useResetUserPassword, useResendVerification, useBulkDeleteUsers, useAuth, useIsPlatformAdmin, useProjects, useNotifications, useUnlockUserTimesheet, useDepartments, useCreateDepartment, useDeleteDepartment, useLeaveTypes, useCreateLeaveType, useUpdateLeaveType, useDeleteLeaveType, useClients } from '@/hooks';
import { KeyRound } from 'lucide-react';
import { timeentriesAPI, ingestionAPI } from '@/api';
import { IngestionTimesheetSummary, Project, TimeEntry, User, UserRole } from '@/types';


const extractErrorMessage = (err: unknown): string => {
  if (typeof err !== 'object' || err === null || !('response' in err)) return 'An error occurred';
  const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    return first.msg ?? 'Validation error';
  }
  return 'An error occurred';
};

type UserMutationPayload = {
  full_name: string;
  // Email is optional in the patch — omit the key entirely to leave
  // the existing value untouched. We never send null because the
  // server-side User shape doesn't model it.
  email?: string;
  title?: string | null;
  department?: string | null;
  role: UserRole;
  // Multi-role: full set of allowed roles. The active role lives in
  // `role`; this is the menu the user can flip between via the
  // post-login portal picker and topbar Switch chip.
  roles?: UserRole[];
  is_active: boolean;
  can_review: boolean;
  is_external: boolean;
  manager_id?: number | null;
  project_ids?: number[];
  default_client_id?: number | null;
};

const TENANT_ROLES: UserRole[] = ['EMPLOYEE', 'MANAGER', 'SENIOR_MANAGER', 'CEO', 'ADMIN'];
const ALL_ROLES: UserRole[] = [...TENANT_ROLES, 'PLATFORM_ADMIN'];

type UserActionMenuProps = {
  isOpen: boolean;
  onToggle: () => void;
  onClose: () => void;
  canEdit: boolean;
  canManage: boolean;
  isResendDisabled: boolean;
  resendTooltip: string;
  onEdit: () => void;
  onResend: () => void;
  onResetPassword: () => void;
  onDelete: () => void;
};

// Row-level actions dropdown. Flips upward when opening near the viewport
// bottom so the menu never gets clipped by the table's overflow-hidden wrapper.
const UserActionMenu: React.FC<UserActionMenuProps> = ({
  isOpen, onToggle, onClose, canEdit, canManage,
  isResendDisabled, resendTooltip,
  onEdit, onResend, onResetPassword, onDelete,
}) => {
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const [openUp, setOpenUp] = React.useState(false);

  React.useEffect(() => {
    if (!isOpen || !buttonRef.current) return;
    const btnRect = buttonRef.current.getBoundingClientRect();
    // Walk up to find the nearest overflow-clipped ancestor. That's what
    // actually bounds the dropdown — not the viewport — because the user
    // list container is overflow-hidden.
    let bound = window.innerHeight;
    let node: HTMLElement | null = buttonRef.current.parentElement;
    while (node) {
      const style = window.getComputedStyle(node);
      if (style.overflowY !== 'visible' && style.overflowY !== 'clip' && node !== document.body) {
        bound = Math.min(bound, node.getBoundingClientRect().bottom);
      }
      node = node.parentElement;
    }
    const spaceBelow = bound - btnRect.bottom;
    const menuHeight = 200; // approx height for up to 4 items + padding
    setOpenUp(spaceBelow < menuHeight && btnRect.top > menuHeight);
  }, [isOpen]);

  const item = (onClick: () => void, icon: React.ReactNode, label: string, extra?: { danger?: boolean; disabled?: boolean; title?: string }) => (
    <button
      onClick={() => { onClose(); onClick(); }}
      disabled={extra?.disabled}
      title={extra?.title}
      className={`flex w-full items-center gap-2 px-3 py-2 text-sm text-left hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed ${extra?.danger ? 'text-destructive hover:bg-destructive/10' : 'text-foreground'}`}
    >
      {icon} {label}
    </button>
  );

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        onClick={onToggle}
        className="p-1.5 rounded hover:bg-muted"
        title="Actions"
        aria-label="User actions"
      >
        <MoreVertical className="w-4 h-4" />
      </button>
      {isOpen && (
        <div
          className={`absolute right-0 z-20 min-w-[180px] rounded-lg border border-border bg-card shadow-lg py-1 ${openUp ? 'bottom-full mb-1' : 'top-full mt-1'}`}
        >
          {canEdit && item(onEdit, <Pencil className="w-3.5 h-3.5" />, 'Edit')}
          {canManage && item(onResend, <MailCheck className="w-3.5 h-3.5" />, 'Resend verification', { disabled: isResendDisabled, title: resendTooltip })}
          {canManage && item(onResetPassword, <KeyRound className="w-3.5 h-3.5" />, 'Reset password')}
          {canManage && item(onDelete, <Trash2 className="w-3.5 h-3.5" />, 'Delete', { danger: true })}
        </div>
      )}
    </div>
  );
};

const getAllowedSupervisorRoles = (role: UserRole): UserRole[] => {
  if (role === 'EMPLOYEE') return ['MANAGER', 'SENIOR_MANAGER', 'CEO', 'ADMIN'];
  if (role === 'MANAGER') return ['SENIOR_MANAGER', 'CEO'];
  if (role === 'SENIOR_MANAGER') return ['CEO'];
  if (role === 'ADMIN') return ['MANAGER', 'SENIOR_MANAGER', 'CEO', 'ADMIN'];
  return [];
};

const normalizeDepartment = (value?: string | null): string => (value ?? '').trim().toLowerCase();

const isSupervisorCompatibleForRoleAndDepartment = (
  userRole: UserRole,
  _userDepartment: string,
  supervisor: User,
): boolean => {
  const allowedSupervisorRoles = getAllowedSupervisorRoles(userRole);
  return allowedSupervisorRoles.includes(supervisor.role);
};

const roleBadge = (role: UserRole, allRoles?: UserRole[] | null) => {
  const styles: Record<UserRole, string> = {
    EMPLOYEE: 'bg-[var(--bg-surface-3)] text-[var(--text-secondary)]',
    MANAGER: 'bg-[var(--info-light)] text-[var(--info)]',
    SENIOR_MANAGER: 'bg-[var(--info-light)] text-[var(--info)]',
    CEO: 'bg-[var(--danger-light)] text-[var(--danger)]',
    ADMIN: 'bg-[var(--accent-light)] text-[var(--accent-blue)]',
    PLATFORM_ADMIN: 'bg-[var(--accent-light)] text-[var(--accent-blue)]',
  };
  // The user may carry additional roles on top of the active one
  // (multi-role accounts). When present, render a small "+N more"
  // chip listing the others as a tooltip.
  const extras = (allRoles ?? []).filter((r) => r !== role);
  return (
    <span className="inline-flex items-center gap-1.5 flex-wrap">
      <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium ${styles[role]}`}>
        {(role === 'ADMIN' || role === 'PLATFORM_ADMIN') && <ShieldCheck className="w-3 h-3" />}
        {role === 'MANAGER' && <UserCircle className="w-3 h-3" />}
        {role}
      </span>
      {extras.length > 0 && (
        <span
          className="inline-flex items-center rounded-full border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary"
          title={`Also: ${extras.join(', ')}`}
        >
          +{extras.length}
        </span>
      )}
    </span>
  );
};

type Audience = 'internal' | 'external' | null;

type FormState = {
  full_name: string;
  email: string;
  username: string;
  title: string;
  department: string;
  role: UserRole;
  // Additional roles this user can act as on top of the primary `role`.
  // The portal picker shows up at login when the combined set has more
  // than one entry. Single-role users keep this empty.
  additional_roles: UserRole[];
  is_active: boolean;
  can_review: boolean;
  // Internal vs External selection. Null forces the admin to pick;
  // the rest of the form is disabled until they do. Persisted as
  // is_external on submit (internal -> false, external -> true).
  audience: Audience;
  manager_id: number | null;
  project_ids: number[];
  default_client_id: number | null;
};

// Roles that can be added on top of the primary role. EMPLOYEE and
// PLATFORM_ADMIN are intentionally excluded: nobody asks for an
// "employee" portal on top of a manager account, and platform-admin
// is its own identity (no tenant_id).
const ADDITIONAL_ROLE_OPTIONS: UserRole[] = ['MANAGER', 'SENIOR_MANAGER', 'CEO', 'ADMIN'];

const emptyForm = (): FormState => ({
  full_name: '',
  email: '',
  username: '',
  title: '',
  department: '',
  role: 'EMPLOYEE',
  additional_roles: [],
  is_active: true,
  can_review: false,
  // Forces the admin to pick Internal or External before the rest of
  // the form is meaningful. Saved as is_external on submit.
  audience: null,
  manager_id: null,
  project_ids: [],
  default_client_id: null,
});

export const AdminPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const { user: currentUser, refreshUser } = useAuth();
  const { data: users, isLoading, error, refetch: refetchUsers } = useUsers();
  const { data: projects, isLoading: projectsLoading, error: projectsError } = useProjects({ limit: 500 });
  const { data: notificationsSummary } = useNotifications();
  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const deleteUser = useDeleteUser();
  const resetPassword = useResetUserPassword();
  const resendVerification = useResendVerification();
  const bulkDeleteUsers = useBulkDeleteUsers();
  const { data: departments = [] } = useDepartments();
  const { data: clientsList = [] } = useClients();
  const createDepartment = useCreateDepartment();
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [resetPasswordUserId, setResetPasswordUserId] = useState<number | null>(null);
  const [actionMenuUserId, setActionMenuUserId] = useState<number | null>(null);
  const [resetPasswordValue, setResetPasswordValue] = useState('');
  const [resetPasswordError, setResetPasswordError] = useState('');

  const toggleUserSelection = (userId: number) => {
    setSelectedUserIds((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  };

  const selectAllUsers = () => {
    const ids = filtered
      .filter((u) => u.id !== currentUser?.id)
      .map((u) => u.id);
    setSelectedUserIds(new Set(ids));
  };

  const clearSelection = () => setSelectedUserIds(new Set());

  const handleBulkDelete = async () => {
    if (selectedUserIds.size === 0) return;
    const confirmed = window.confirm(`Are you sure you want to delete ${selectedUserIds.size} user(s)? This action cannot be undone.`);
    if (!confirmed) return;
    await bulkDeleteUsers.mutateAsync(Array.from(selectedUserIds));
    setSelectedUserIds(new Set());
  };

  const isPlatformAdmin = useIsPlatformAdmin();
  const isAdminUser = currentUser?.role === 'ADMIN' || currentUser?.role === 'PLATFORM_ADMIN';
  const roles = isPlatformAdmin ? ALL_ROLES : TENANT_ROLES;
  const canManageEmployeeProjects =
    currentUser?.role === 'ADMIN' || currentUser?.role === 'PLATFORM_ADMIN' ||
    currentUser?.role === 'MANAGER' ||
    currentUser?.role === 'SENIOR_MANAGER' ||
    currentUser?.role === 'CEO';

  React.useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  const [showModal, setShowModal] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [selectedUserDetails, setSelectedUserDetails] = useState<User | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [formError, setFormError] = useState('');
  const [search, setSearch] = useState(() => searchParams.get('search') ?? '');
  const [roleFilter, setRoleFilter] = useState<'ALL' | UserRole>(() => {
    const role = searchParams.get('role');
    if (role === 'EMPLOYEE' || role === 'MANAGER' || role === 'SENIOR_MANAGER' || role === 'CEO' || role === 'ADMIN' || role === 'PLATFORM_ADMIN') {
      return role as UserRole;
    }
    return 'ALL';
  });
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'ACTIVE' | 'INACTIVE'>(() => {
    const status = searchParams.get('status');
    if (status === 'ACTIVE' || status === 'INACTIVE') {
      return status;
    }
    return 'ALL';
  });
  // Attention filter — driven by the dashboard Action Queue links so a
  // click-through into user management lands the admin on the exact
  // subset the queue called out (no_manager rows, stale unverified
  // invites). 'NONE' is the default.
  const [attentionFilter, setAttentionFilter] = useState<'NONE' | 'NO_MANAGER' | 'UNVERIFIED'>(() => {
    const status = searchParams.get('status');
    if (status === 'NO_MANAGER') return 'NO_MANAGER';
    if ((searchParams.get('verified') ?? '').toUpperCase() === 'NO') return 'UNVERIFIED';
    return 'NONE';
  });
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [showNoProjectModal, setShowNoProjectModal] = useState(false);
  // Post-create confirmation state. We carry enough context to pick
  // the right copy: synthetic placeholder addresses must never be
  // shown to the admin, and the line about "verification email sent"
  // only fires when the backend actually sent one.
  const [createdUserSummary, setCreatedUserSummary] = useState<{
    fullName: string;
    email: string;
    isExternal: boolean;
    verificationEmailSent: boolean;
  } | null>(null);
  const userListSectionRef = React.useRef<HTMLDivElement | null>(null);

  // Team Timesheets tab state
  const [activeTab, setActiveTab] = useState<'users' | 'timesheets' | 'departments' | 'leave_types'>('users');
  const deleteDepartment = useDeleteDepartment();
  const [newDepartmentName, setNewDepartmentName] = useState('');

  const { data: leaveTypesAll = [] } = useLeaveTypes(true);
  const createLeaveType = useCreateLeaveType();
  const updateLeaveType = useUpdateLeaveType();
  const deleteLeaveType = useDeleteLeaveType();
  const [newLeaveTypeLabel, setNewLeaveTypeLabel] = useState('');
  const [newLeaveTypeColor, setNewLeaveTypeColor] = useState('#6b7280');
  const [tsEmployeeId, setTsEmployeeId] = useState<number | ''>('');
  const [tsStartDate, setTsStartDate] = useState(format(startOfMonth(new Date()), 'yyyy-MM-dd'));
  const [tsEndDate, setTsEndDate] = useState(format(endOfMonth(new Date()), 'yyyy-MM-dd'));
  const [tsStatus, setTsStatus] = useState('');
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [sourceAttachmentId, setSourceAttachmentId] = useState<number | null>(null);
  const [sourceAttachmentFilename, setSourceAttachmentFilename] = useState<string>('');
  const [sourceAttachmentUrl, setSourceAttachmentUrl] = useState<string | null>(null);
  const [sourceAttachmentLoading, setSourceAttachmentLoading] = useState(false);

  const { data: teamEntries = [], isFetching: tsLoading } = useQuery({
    queryKey: ['team-timesheets', tsEmployeeId, tsStartDate, tsEndDate, tsStatus],
    queryFn: () =>
      timeentriesAPI.listAll({
        user_id: tsEmployeeId !== '' ? tsEmployeeId : undefined,
        start_date: tsStartDate || undefined,
        end_date: tsEndDate || undefined,
        status: tsStatus || undefined,
        sort_by: 'entry_date',
        sort_order: 'desc',
        limit: 500,
      }).then((r: { data: TimeEntry[] }) => r.data),
    enabled: activeTab === 'timesheets',
  });

  // Approved ingestion timesheets with no line items (total-hours-only PDFs)
  const { data: approvedIngestionTimesheets = [] } = useQuery({
    queryKey: ['team-timesheets-ingestion-no-entries', tsEmployeeId, tsStartDate, tsEndDate],
    queryFn: () =>
      ingestionAPI.listTimesheets({
        status_filter: 'approved',
        employee_id: tsEmployeeId !== '' ? tsEmployeeId : undefined,
        limit: 200,
      }).then((r: { data: IngestionTimesheetSummary[] }) =>
        r.data.filter((ts) => !ts.time_entries_created && ts.total_hours)
      ),
    enabled: activeTab === 'timesheets' && (!tsStatus || tsStatus === 'APPROVED'),
  });

  const unlockUser = useUnlockUserTimesheet();

  React.useEffect(() => {
    const nextSearch = searchParams.get('search') ?? '';
    const nextRole = searchParams.get('role');
    const nextStatus = searchParams.get('status');
    const nextVerified = (searchParams.get('verified') ?? '').toUpperCase();

    setSearch(nextSearch);
    setRoleFilter(nextRole === 'EMPLOYEE' || nextRole === 'MANAGER' || nextRole === 'SENIOR_MANAGER' || nextRole === 'CEO' || nextRole === 'ADMIN' || nextRole === 'PLATFORM_ADMIN' ? (nextRole as UserRole) : 'ALL');
    setStatusFilter(nextStatus === 'ACTIVE' || nextStatus === 'INACTIVE' ? nextStatus : 'ALL');

    // Attention sub-filters take precedence over plain status. A
    // dashboard chip pointing at "12 users without a manager" lands
    // here with ?status=NO_MANAGER; an unverified-invitations chip
    // arrives with ?verified=NO. Anything else clears the attention
    // filter.
    if (nextStatus === 'NO_MANAGER') {
      setAttentionFilter('NO_MANAGER');
    } else if (nextVerified === 'NO') {
      setAttentionFilter('UNVERIFIED');
    } else {
      setAttentionFilter('NONE');
    }
  }, [searchParams]);

  React.useEffect(() => {
    if (isLoading || projectsLoading || !users) return;

    const userIdParam = searchParams.get('userId');
    const parsedUserId = userIdParam ? Number(userIdParam) : NaN;
    if (!Number.isFinite(parsedUserId)) {
      return;
    }

    const matchedUser = users.find((candidate) => candidate.id === parsedUserId) ?? null;
    setSelectedUserDetails(matchedUser);
  }, [searchParams, isLoading, projectsLoading, users]);

  React.useEffect(() => {
    if (isLoading || projectsLoading) return;

    const hasDashboardFilter =
      searchParams.has('userId') ||
      searchParams.has('role') ||
      searchParams.has('status') ||
      searchParams.has('search');

    if (!hasDashboardFilter) return;

    requestAnimationFrame(() => {
      userListSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, [searchParams, isLoading, projectsLoading]);

  React.useEffect(() => {
    if (actionMenuUserId === null) return;
    const close = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest('[data-user-action-menu]')) setActionMenuUserId(null);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [actionMenuUserId]);

  if (isLoading || projectsLoading) return <Loading />;
  if (error || projectsError) return <Error message="Failed to load user management data" />;

  const allowedSupervisorRoles = getAllowedSupervisorRoles(form.role);
  const supervisors = (users ?? [])
    .filter((u) => allowedSupervisorRoles.includes(u.role))
    .filter((u) => u.id !== editingUser?.id)
    .sort((a, b) => a.full_name.localeCompare(b.full_name));
  const usersByManager = (users ?? []).reduce<Record<number, User[]>>((acc, user) => {
    if (!user.manager_id) return acc;
    if (!acc[user.manager_id]) acc[user.manager_id] = [];
    acc[user.manager_id].push(user);
    return acc;
  }, {});
  Object.values(usersByManager).forEach((items) => items.sort((a, b) => a.full_name.localeCompare(b.full_name)));

  const visibleUserIds = new Set((users ?? []).map((u) => u.id));
  const topLevelUsers = (users ?? [])
    .filter((u) => !u.manager_id || !visibleUserIds.has(u.manager_id))
    .sort((a, b) => a.full_name.localeCompare(b.full_name));

  const activeProjects = (projects ?? []).filter((project: Project) => project.is_active);
  const normalizedSearch = search.trim().toLowerCase();

  const searchSuggestions = Array.from(
    new Set(
      (users ?? []).flatMap((u: User) =>
        [u.full_name, u.email, u.department].filter((v): v is string => Boolean(v))
      )
    )
  ).sort();

  // Attention sub-filter predicate. Shapes match the AdminActionQueue
  // rules so the click-through subset is exactly what the queue badge
  // is counting.
  const STALE_INVITE_DAYS = 7;
  const STALE_INVITE_CUTOFF_MS = Date.now() - STALE_INVITE_DAYS * 24 * 60 * 60 * 1000;
  const ORPHAN_ROLES = new Set<UserRole>(['EMPLOYEE', 'MANAGER', 'SENIOR_MANAGER']);
  const matchesAttention = (u: User): boolean => {
    if (attentionFilter === 'NO_MANAGER') {
      return Boolean(u.is_active) && ORPHAN_ROLES.has(u.role) && u.manager_id == null;
    }
    if (attentionFilter === 'UNVERIFIED') {
      if (!u.is_active || u.email_verified) return false;
      const created = u.created_at ? Date.parse(u.created_at) : NaN;
      return Number.isFinite(created) && created < STALE_INVITE_CUTOFF_MS;
    }
    return true;
  };

  const filtered = (users ?? []).filter((u) => {
    const matchesSearch =
      normalizedSearch.length === 0 ||
      u.full_name.toLowerCase().includes(normalizedSearch) ||
      u.email.toLowerCase().includes(normalizedSearch) ||
      u.role.toLowerCase().includes(normalizedSearch) ||
      (u.department ?? '').toLowerCase().includes(normalizedSearch);

    const matchesRole = roleFilter === 'ALL' || u.role === roleFilter;
    const matchesStatus =
      statusFilter === 'ALL' ||
      (statusFilter === 'ACTIVE' && u.is_active) ||
      (statusFilter === 'INACTIVE' && !u.is_active);

    return matchesSearch && matchesRole && matchesStatus && matchesAttention(u);
  });

  const userManagementAlerts = (notificationsSummary?.items ?? []).filter(
    (item) => item.route === '/admin' && !item.is_read
  );
  const employeesWithoutProjects = (users ?? []).filter(
    (u) => u.role === 'EMPLOYEE' && u.is_active && (u.project_ids ?? []).length === 0
  );
  const usersById = (users ?? []).reduce<Record<number, User>>((acc, user) => {
    acc[user.id] = user;
    return acc;
  }, {});

  const getManagerDisplayName = (managerId?: number | null): string => {
    if (!managerId) return 'Unassigned';
    if (usersById[managerId]?.full_name) return usersById[managerId].full_name;
    if (currentUser?.id === managerId) return currentUser.full_name;
    return 'Unknown';
  };

  const getUserProjectDetails = (user: User): Project[] => {
    const assignedIds = user.project_ids ?? [];
    return (projects ?? []).filter((project: Project) => assignedIds.includes(project.id));
  };

  const openCreate = () => {
    if (!isAdminUser) return;
    setEditingUser(null);
    setForm(emptyForm());
    setFormError('');
    setShowModal(true);
  };

  const openEdit = (u: User) => {
    if (!isAdminUser && (!canManageEmployeeProjects || u.role === 'ADMIN' || u.role === 'PLATFORM_ADMIN')) {
      return;
    }

    setEditingUser(u);
    const normalizedDepartment = normalizeDepartment(u.department);
    const normalizedManagerId = (() => {
      if (!u.manager_id) return null;
      const manager = (users ?? []).find((candidate) => candidate.id === u.manager_id);
      if (!manager) return null;
      if (!isSupervisorCompatibleForRoleAndDepartment(u.role, normalizedDepartment, manager)) return null;
      return u.manager_id;
    })();

    // Hydrate additional_roles from the user's roles list, excluding
    // the primary active role. Defensively dedupe and filter to the
    // set that the UI knows how to render.
    const allRoles = (u.roles ?? []).filter((r): r is UserRole => Boolean(r));
    const additional = Array.from(new Set(allRoles.filter((r) => r !== u.role)))
      .filter((r) => ADDITIONAL_ROLE_OPTIONS.includes(r));

    setForm({
      full_name: u.full_name,
      email: u.email,
      username: u.username ?? '',
      title: u.title ?? '',
      department: u.department ?? '',
      role: u.role,
      additional_roles: additional,
      is_active: u.is_active,
      can_review: u.can_review ?? false,
      audience: (u.is_external ?? false) ? 'external' : 'internal',
      manager_id: normalizedManagerId,
      project_ids: u.project_ids ?? [],
      default_client_id: u.default_client_id ?? null,
    });
    setFormError('');
    setShowModal(true);
  };

  const closeModal = () => {
    setShowModal(false);
    setEditingUser(null);
    setFormError('');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');

    if (editingUser && isProjectOnlyEdit) {
      try {
        await updateUser.mutateAsync({
          id: editingUser.id,
          data: {
            project_ids: form.project_ids,
          },
        });
        await refetchUsers();
        closeModal();
      } catch (err: unknown) {
        setFormError(extractErrorMessage(err));
      }
      return;
    }

    const normalizedFullName = form.full_name.trim();
    const normalizedEmail = form.email.trim().toLowerCase();
    const normalizedUsername = form.username.trim().toLowerCase();
    const normalizedTitle = form.title.trim();
    const normalizedDepartment = form.department.trim();

    // Only two fields are mandatory: full name and the audience (the
    // Internal vs External chip). Everything else is optional and the
    // backend synthesizes safe placeholders for blank email/username.
    if (!normalizedFullName) {
      setFormError('Full name is required');
      return;
    }
    if (form.audience === null) {
      setFormError('Pick Internal or External before saving');
      return;
    }

    // Username, when supplied, still needs the platform's 3-char
    // minimum so the admin doesn't accidentally save something that
    // would later 422 on update.
    if (normalizedUsername && normalizedUsername.length < 3) {
      setFormError('Username must be at least 3 characters');
      return;
    }

    // Combined roles list: primary first, additional after, deduped.
    // The portal picker uses this set to decide whether to show.
    const combinedRoles: UserRole[] = Array.from(
      new Set([form.role, ...form.additional_roles]),
    );

    const isExternal = form.audience === 'external';

    // Detect "admin just added a real email to a user that had none."
    // Backend synthesizes ``no-email+...@local.invalid`` for users
    // created without an email. If that's what they had before and the
    // admin typed a real address now, offer to send the verification
    // email immediately. Saying no leaves the email on file; the admin
    // can resend later from the user-management table.
    const previousEmail = (editingUser?.email ?? '').toLowerCase();
    const previousWasPlaceholder = previousEmail === '' || previousEmail.endsWith('@local.invalid');
    const emailJustAdded = (
      Boolean(editingUser)
      && !isExternal
      && previousWasPlaceholder
      && Boolean(normalizedEmail)
      && !normalizedEmail.endsWith('@local.invalid')
    );

    try {
      if (editingUser) {
        const payload: UserMutationPayload = {
          full_name: normalizedFullName,
          // Only include email in the patch when the admin actually
          // typed one. Omitting leaves the existing value untouched.
          ...(normalizedEmail ? { email: normalizedEmail } : {}),
          title: normalizedTitle || null,
          department: normalizedDepartment || null,
          role: form.role,
          roles: combinedRoles,
          is_active: form.is_active,
          can_review: isExternal ? false : form.can_review,
          is_external: isExternal,
          manager_id: isExternal ? null : form.manager_id,
          project_ids: isExternal || form.role !== 'EMPLOYEE' ? [] : form.project_ids,
          default_client_id: form.default_client_id,
        };
        await updateUser.mutateAsync({ id: editingUser.id, data: payload });

        // After a successful save, ask the admin if they want to fire
        // the verification email now. They can always trigger it later
        // from the user-management table's resend action.
        if (emailJustAdded) {
          // window.confirm is intentional: the admin's flow is "save
          // then react to a single decision," and a heavier modal here
          // would interrupt the table refresh. Confirm dismisses
          // cleanly on Esc / Cancel and the row is already saved.
          const sendNow = window.confirm(
            `Send a verification email to ${normalizedEmail} now?\n\n`
            + 'OK = send now. Cancel = save the email but skip verification (you can resend from the table later).',
          );
          if (sendNow) {
            try {
              await resendVerification.mutateAsync(editingUser.id);
            } catch (err) {
              // Don't fail the whole save if the email send fails;
              // surface as an inline note instead.
              setFormError(`Saved, but verification email failed: ${extractErrorMessage(err)}`);
            }
          }
        }
      } else {
        if (!isAdminUser) {
          setFormError('Only admins can create users');
          return;
        }
        const result = await createUser.mutateAsync({
          ...form,
          full_name: normalizedFullName,
          // Send blank as undefined so the backend synthesizes a
          // placeholder rather than failing EmailStr validation on "".
          email: normalizedEmail || undefined,
          username: normalizedUsername || undefined,
          title: normalizedTitle || null,
          department: normalizedDepartment || null,
          can_review: isExternal ? false : form.can_review,
          is_external: isExternal,
          manager_id: isExternal ? null : form.manager_id,
          project_ids: isExternal || form.role !== 'EMPLOYEE' ? [] : form.project_ids,
          default_client_id: form.default_client_id,
        });
        // If the admin checked any additional portals, patch the new
        // user with the combined roles list. Backend UserCreate doesn't
        // accept a roles list (defaults to [role]), so we follow up with PUT.
        if (form.additional_roles.length > 0 && result?.user?.id) {
          await updateUser.mutateAsync({
            id: result.user.id,
            data: { roles: combinedRoles },
          });
        }
        setCreatedUserSummary({
          fullName: result?.user?.full_name || normalizedFullName,
          email: result?.user?.email || normalizedEmail || '',
          isExternal: Boolean(result?.user?.is_external),
          // Backend sets verification_email_sent=true only when it
          // actually queued an email (internal + active + real
          // address). Use it directly so the modal copy matches.
          verificationEmailSent: Boolean(result?.verification_email_sent),
        });
      }
      await refetchUsers();
      closeModal();
    } catch (err: unknown) {
      setFormError(extractErrorMessage(err));
    }
  };

  const handleToggleActive = async (u: User) => {
    if (!isAdminUser) return;
    await updateUser.mutateAsync({ id: u.id, data: { is_active: !u.is_active } });
  };

  const handleDelete = async (id: number) => {
    if (!isAdminUser) return;
    await deleteUser.mutateAsync(id);
    setConfirmDeleteId(null);
  };

  const handleResetPassword = async () => {
    if (!resetPasswordUserId || !resetPasswordValue.trim()) return;
    setResetPasswordError('');
    if (resetPasswordValue.length < 8) {
      setResetPasswordError('Password must be at least 8 characters.');
      return;
    }
    try {
      await resetPassword.mutateAsync({ id: resetPasswordUserId, newPassword: resetPasswordValue });
      setResetPasswordUserId(null);
      setResetPasswordValue('');
    } catch (err: unknown) {
      setResetPasswordError(extractErrorMessage(err));
    }
  };

  const canEditUser = (u: User) => {
    if (isAdminUser) return true;
    return canManageEmployeeProjects && u.role !== 'ADMIN' && u.role !== 'PLATFORM_ADMIN';
  };

  const handleResendVerification = async (u: User) => {
    setActionMenuUserId(null);
    try {
      await resendVerification.mutateAsync(u.id);
      alert(`Verification email resent to ${u.email}.`);
    } catch (err: unknown) {
      alert(extractErrorMessage(err));
    }
  };

  const isProjectOnlyEdit = Boolean(editingUser && !isAdminUser);

  const handleProjectToggle = (projectId: number) => {
    setForm((current) => ({
      ...current,
      project_ids: current.project_ids.includes(projectId)
        ? current.project_ids.filter((id) => id !== projectId)
        : [...current.project_ids, projectId],
    }));
  };

  const scrollToUserList = () => {
    requestAnimationFrame(() => {
      userListSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  };

  const applyUserListFilter = (nextRole: 'ALL' | UserRole, nextStatus: 'ALL' | 'ACTIVE' | 'INACTIVE') => {
    setSearch('');
    setRoleFilter(nextRole);
    setStatusFilter(nextStatus);
    scrollToUserList();
  };

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-3xl font-bold">User Management</h1>
            <p className="text-sm text-muted-foreground mt-1">{(users ?? []).length} total users</p>
          </div>
          {isAdminUser && activeTab === 'users' && (
            <button
              onClick={openCreate}
              className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 shadow"
            >
              <PlusCircle className="w-4 h-4" />
              New User
            </button>
          )}
        </div>

        {/* Tab switcher */}
        <div className="flex gap-1 border-b mb-6">
          <button
            onClick={() => setActiveTab('users')}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition ${
              activeTab === 'users'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <UserCircle className="w-4 h-4" />Users
          </button>
          <button
            onClick={() => setActiveTab('timesheets')}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition ${
              activeTab === 'timesheets'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <Clock className="w-4 h-4" />Team Timesheets
          </button>
          <button
            onClick={() => setActiveTab('departments')}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition ${
              activeTab === 'departments'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <Building2 className="w-4 h-4" />Departments
          </button>
          <button
            onClick={() => setActiveTab('leave_types')}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition ${
              activeTab === 'leave_types'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <Paperclip className="w-4 h-4" />Leave Types
          </button>
        </div>

        {/* Team Timesheets tab */}
        {activeTab === 'timesheets' && (
          <div>
            {/* Filters */}
            <div className="flex flex-wrap gap-3 mb-5">
              <select
                className="rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                value={tsEmployeeId}
                onChange={(e) => setTsEmployeeId(e.target.value === '' ? '' : Number(e.target.value))}
              >
                <option value="">All Employees</option>
                {(users ?? [])
                  .filter((u) => u.is_active && u.role === 'EMPLOYEE')
                  .sort((a, b) => a.full_name.localeCompare(b.full_name))
                  .map((u) => (
                    <option key={u.id} value={u.id}>{u.full_name}</option>
                  ))}
              </select>

              <input
                type="date"
                className="rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                value={tsStartDate}
                onChange={(e) => setTsStartDate(e.target.value)}
              />
              <input
                type="date"
                className="rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                value={tsEndDate}
                onChange={(e) => setTsEndDate(e.target.value)}
              />

              <select
                className="rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                value={tsStatus}
                onChange={(e) => setTsStatus(e.target.value)}
              >
                <option value="">All Statuses</option>
                <option value="DRAFT">Draft</option>
                <option value="SUBMITTED">Submitted</option>
                <option value="APPROVED">Approved</option>
                <option value="REJECTED">Rejected</option>
              </select>
            </div>

            {/* Entries table — grouped by employee + project, expandable */}
            {(() => {
              type AggRow = {
                key: string;
                employeeName: string;
                projectName: string;
                totalHours: number;
                minDate: string;
                maxDate: string;
                statuses: Set<string>;
                entries: TimeEntry[];
                ingestionOnly?: boolean;
                ingestionId?: number;
                attachmentId?: number | null;
                attachmentFilename?: string;
              };
              const map = new Map<string, AggRow>();
              (teamEntries as TimeEntry[]).forEach((entry) => {
                const k = `${entry.user_id}-${entry.project_id}`;
                const existing = map.get(k);
                if (existing) {
                  existing.totalHours += Number(entry.hours);
                  if (entry.entry_date < existing.minDate) existing.minDate = entry.entry_date;
                  if (entry.entry_date > existing.maxDate) existing.maxDate = entry.entry_date;
                  existing.statuses.add(entry.status);
                  existing.entries.push(entry);
                } else {
                  map.set(k, {
                    key: k,
                    employeeName: entry.user?.full_name ?? '—',
                    projectName: entry.project?.name ?? '—',
                    totalHours: Number(entry.hours),
                    minDate: entry.entry_date,
                    maxDate: entry.entry_date,
                    statuses: new Set([entry.status]),
                    entries: [entry],
                  });
                }
              });

              // Merge approved ingestion timesheets that have no line entries (summary-only PDFs)
              const dateInRange = (ts: IngestionTimesheetSummary) => {
                const start = ts.period_start ?? ts.reviewed_at?.slice(0, 10) ?? null;
                const end = ts.period_end ?? start;
                if (!start) return true;
                if (tsStartDate && end && end < tsStartDate) return false;
                if (tsEndDate && start > tsEndDate) return false;
                return true;
              };
              (approvedIngestionTimesheets as IngestionTimesheetSummary[])
                .filter(dateInRange)
                .forEach((ts) => {
                  const k = `ingestion-${ts.id}`;
                  const periodStart = ts.period_start ?? ts.reviewed_at?.slice(0, 10) ?? '';
                  const periodEnd = ts.period_end ?? periodStart;
                  map.set(k, {
                    key: k,
                    employeeName: ts.employee_name ?? ts.extracted_employee_name ?? '—',
                    projectName: ts.client_name ?? '—',
                    totalHours: Number(ts.total_hours ?? 0),
                    minDate: periodStart,
                    maxDate: periodEnd,
                    statuses: new Set(['APPROVED']),
                    entries: [],
                    ingestionOnly: true,
                    ingestionId: ts.id,
                    attachmentId: ts.attachment_id,
                    attachmentFilename: ts.subject ?? `Timesheet-${ts.id}`,
                  });
                });

              const rows = Array.from(map.values());
              const statusPriority = (s: Set<string>) => {
                if (s.has('REJECTED')) return 'REJECTED';
                if (s.has('DRAFT')) return 'DRAFT';
                if (s.has('SUBMITTED')) return 'SUBMITTED';
                return 'APPROVED';
              };
              const toggleRow = (key: string) => {
                setExpandedRows((prev) => {
                  const next = new Set(prev);
                  next.has(key) ? next.delete(key) : next.add(key);
                  return next;
                });
              };
              return (
                <div className="rounded-xl border bg-white shadow-sm overflow-hidden">
                  {tsLoading ? (
                    <p className="text-sm text-slate-400 p-6 text-center">Loading…</p>
                  ) : rows.length === 0 ? (
                    <p className="text-sm text-slate-400 p-6 text-center">No time entries found for the selected filters.</p>

                  ) : (
                    <table className="w-full text-sm">
                      <thead className="bg-slate-50 border-b text-left">
                        <tr>
                          <th className="px-4 py-3 font-semibold text-slate-700 w-6"></th>
                          <th className="px-4 py-3 font-semibold text-slate-700">Employee</th>
                          <th className="px-4 py-3 font-semibold text-slate-700">Project</th>
                          <th className="px-4 py-3 font-semibold text-slate-700">Date Range</th>
                          <th className="px-4 py-3 font-semibold text-slate-700">Days</th>
                          <th className="px-4 py-3 font-semibold text-slate-700">Total Hours</th>
                          <th className="px-4 py-3 font-semibold text-slate-700">Status</th>
                          <th className="px-4 py-3 font-semibold text-slate-700 w-10"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((row) => {
                          const status = statusPriority(row.statuses);
                          const isExpanded = expandedRows.has(row.key);
                          const safeDate = (d: string) => d ? new Date(d + 'T00:00:00') : null;
                          const minD = safeDate(row.minDate);
                          const maxD = safeDate(row.maxDate);
                          const dateRange = !minD ? '—'
                            : !maxD || row.minDate === row.maxDate
                              ? format(minD, 'MMM d, yyyy')
                              : `${format(minD, 'MMM d')} – ${format(maxD, 'MMM d, yyyy')}`;
                          const sortedEntries = [...row.entries].sort((a, b) => a.entry_date.localeCompare(b.entry_date));
                          return (
                            <>
                              <tr
                                key={row.key}
                                className={`border-t border-slate-100 ${row.ingestionOnly ? 'bg-amber-50/40' : 'hover:bg-slate-50 cursor-pointer'}`}
                                onClick={() => !row.ingestionOnly && toggleRow(row.key)}
                              >
                                <td className="px-4 py-2.5 text-slate-400 text-xs select-none">
                                  {row.ingestionOnly ? '' : isExpanded ? '▼' : '▶'}
                                </td>
                                <td className="px-4 py-2.5 font-medium text-slate-900">{row.employeeName}</td>
                                <td className="px-4 py-2.5 text-slate-600">{row.projectName}</td>
                                <td className="px-4 py-2.5 text-slate-600">{dateRange}</td>
                                <td className="px-4 py-2.5 text-slate-600">{row.ingestionOnly ? '—' : row.entries.length}</td>
                                <td className="px-4 py-2.5 text-slate-900 font-medium">{row.totalHours}h</td>
                                <td className="px-4 py-2.5">
                                  {row.ingestionOnly ? (
                                    <span className="inline-flex px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700">
                                      APPROVED
                                      <span className="ml-1 text-amber-600 font-normal">(no entries)</span>
                                    </span>
                                  ) : (
                                    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${
                                      status === 'APPROVED' ? 'bg-emerald-100 text-emerald-700' :
                                      status === 'SUBMITTED' ? 'bg-blue-100 text-blue-700' :
                                      status === 'REJECTED' ? 'bg-red-100 text-red-700' :
                                      'bg-slate-100 text-slate-600'
                                    }`}>{row.statuses.size > 1 ? 'MIXED' : status}</span>
                                  )}
                                </td>
                                <td className="px-4 py-2.5">
                                  {row.ingestionOnly && row.attachmentId && (
                                    <button
                                      title="View source timesheet file"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setSourceAttachmentId(row.attachmentId!);
                                        setSourceAttachmentFilename(row.attachmentFilename ?? '');
                                        setSourceAttachmentUrl(null);
                                        setSourceAttachmentLoading(true);
                                        ingestionAPI.getAttachmentFile(row.attachmentId!)
                                          .then((url) => { setSourceAttachmentUrl(url); setSourceAttachmentLoading(false); })
                                          .catch(() => setSourceAttachmentLoading(false));
                                      }}
                                      className="inline-flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
                                    >
                                      <Paperclip className="h-3.5 w-3.5" />
                                    </button>
                                  )}
                                </td>
                              </tr>
                              {!row.ingestionOnly && isExpanded && sortedEntries.map((entry) => {
                                const eStatus = entry.status;
                                return (
                                  <tr key={entry.id} className="bg-slate-50/70 border-t border-slate-100">
                                    <td className="px-4 py-2"></td>
                                    <td className="px-4 py-2 text-slate-400 text-xs">↳</td>
                                    <td className="px-4 py-2 text-slate-500 text-xs">{entry.task?.name ?? '—'}</td>
                                    <td className="px-4 py-2 text-slate-500 text-xs">{format(new Date(entry.entry_date + 'T00:00:00'), 'MMM d, yyyy')}</td>
                                    <td></td>
                                    <td className="px-4 py-2 text-slate-700 text-xs font-medium">{Number(entry.hours)}h</td>
                                    <td className="px-4 py-2">
                                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${
                                        eStatus === 'APPROVED' ? 'bg-emerald-100 text-emerald-700' :
                                        eStatus === 'SUBMITTED' ? 'bg-blue-100 text-blue-700' :
                                        eStatus === 'REJECTED' ? 'bg-red-100 text-red-700' :
                                        'bg-slate-100 text-slate-600'
                                      }`}>{eStatus}</span>
                                    </td>
                                    <td></td>
                                  </tr>
                                );
                              })}
                            </>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              );
            })()}
            <p className="text-xs text-slate-400 mt-2">{teamEntries.length} entries</p>
          </div>
        )}

        {/* Source file slide-over */}
        {sourceAttachmentId !== null && (
          <div className="fixed inset-0 z-50 flex justify-end">
            <div className="absolute inset-0 bg-black/30" onClick={() => { setSourceAttachmentId(null); if (sourceAttachmentUrl) URL.revokeObjectURL(sourceAttachmentUrl); setSourceAttachmentUrl(null); }} />
            <div className="relative bg-white shadow-xl w-full max-w-2xl flex flex-col">
              <div className="flex items-center justify-between px-5 py-4 border-b">
                <div>
                  <p className="text-xs text-slate-400 uppercase tracking-wide font-medium">Source File</p>
                  <p className="font-semibold text-slate-900 truncate max-w-sm">{sourceAttachmentFilename}</p>
                </div>
                <button
                  onClick={() => { setSourceAttachmentId(null); if (sourceAttachmentUrl) URL.revokeObjectURL(sourceAttachmentUrl); setSourceAttachmentUrl(null); }}
                  className="inline-flex h-8 w-8 items-center justify-center rounded hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="flex-1 overflow-auto p-4">
                {sourceAttachmentLoading ? (
                  <div className="flex items-center justify-center h-full text-sm text-slate-400">Loading…</div>
                ) : sourceAttachmentUrl ? (
                  <iframe src={sourceAttachmentUrl} className="h-full w-full border-0 min-h-[70vh]" title={sourceAttachmentFilename} />
                ) : (
                  <div className="flex items-center justify-center h-full text-sm text-slate-400">Failed to load file.</div>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'departments' && (
          <div className="rounded-xl border border-border bg-card shadow-sm p-6 max-w-2xl">
            <div className="mb-4">
              <h3 className="text-base font-semibold">Departments</h3>
              <p className="text-sm text-muted-foreground mt-0.5">Departments shown in the user form dropdown.</p>
            </div>
            <form
              className="flex gap-2 mb-4"
              onSubmit={(e) => {
                e.preventDefault();
                const name = newDepartmentName.trim();
                if (!name) return;
                createDepartment.mutate(name, {
                  onSuccess: () => setNewDepartmentName(''),
                  onError: () => alert('Failed to create department (it may already exist).'),
                });
              }}
            >
              <input
                value={newDepartmentName}
                onChange={(e) => setNewDepartmentName(e.target.value)}
                placeholder="New department name"
                className="field-input flex-1"
              />
              <button type="submit" className="action-button text-sm" disabled={createDepartment.isPending || !newDepartmentName.trim()}>
                Add
              </button>
            </form>
            {departments.length === 0 ? (
              <p className="text-sm text-muted-foreground">No departments yet.</p>
            ) : (
              <ul className="divide-y divide-border">
                {departments.map((d) => (
                  <li key={d.id} className="flex items-center justify-between py-2 text-sm">
                    <span className="text-foreground">{d.name}</span>
                    <button
                      type="button"
                      onClick={() => {
                        if (!window.confirm(`Delete department "${d.name}"? Users currently assigned will keep the value as a legacy reference.`)) return;
                        deleteDepartment.mutate(d.id);
                      }}
                      className="text-xs text-destructive hover:underline"
                      disabled={deleteDepartment.isPending}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {activeTab === 'leave_types' && (
          <div className="rounded-xl border border-border bg-card shadow-sm p-6 max-w-2xl">
            <div className="mb-4">
              <h3 className="text-base font-semibold">Leave types</h3>
              <p className="text-sm text-muted-foreground mt-0.5">Types of time off employees can request. Deactivate to retire a type without deleting historical requests.</p>
            </div>
            <form
              className="flex gap-2 mb-4"
              onSubmit={(e) => {
                e.preventDefault();
                const label = newLeaveTypeLabel.trim();
                if (!label) return;
                createLeaveType.mutate(
                  { label, color: newLeaveTypeColor },
                  {
                    onSuccess: () => {
                      setNewLeaveTypeLabel('');
                      setNewLeaveTypeColor('#6b7280');
                    },
                    onError: () => alert('Failed to create leave type (code may already exist).'),
                  },
                );
              }}
            >
              <input
                value={newLeaveTypeLabel}
                onChange={(e) => setNewLeaveTypeLabel(e.target.value)}
                placeholder="New leave type name (e.g. Bereavement)"
                className="field-input flex-1"
              />
              <input
                type="color"
                value={newLeaveTypeColor}
                onChange={(e) => setNewLeaveTypeColor(e.target.value)}
                className="h-9 w-12 cursor-pointer rounded border border-border"
                title="Pick a color"
              />
              <button type="submit" className="action-button text-sm" disabled={createLeaveType.isPending || !newLeaveTypeLabel.trim()}>
                Add
              </button>
            </form>
            {leaveTypesAll.length === 0 ? (
              <p className="text-sm text-muted-foreground">No leave types yet.</p>
            ) : (
              <ul className="divide-y divide-border">
                {leaveTypesAll.map((lt) => (
                  <li key={lt.id} className="flex items-center gap-3 py-2 text-sm">
                    <span className="inline-block h-3 w-3 rounded-full shrink-0" style={{ backgroundColor: lt.color }} />
                    <span className={`flex-1 ${lt.is_active ? 'text-foreground' : 'text-muted-foreground line-through'}`}>
                      {lt.label}
                      <span className="ml-2 text-xs text-muted-foreground">({lt.code})</span>
                    </span>
                    <button
                      type="button"
                      className="text-xs text-muted-foreground hover:text-foreground"
                      onClick={() => updateLeaveType.mutate({ id: lt.id, data: { is_active: !lt.is_active } })}
                    >
                      {lt.is_active ? 'Deactivate' : 'Reactivate'}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (!window.confirm(`Permanently delete "${lt.label}"? This is only possible if no time-off requests reference it; otherwise deactivate instead.`)) return;
                        deleteLeaveType.mutate(lt.id, {
                          onError: (err: unknown) => {
                            const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
                            alert(detail || 'Failed to delete leave type.');
                          },
                        });
                      }}
                      className="text-xs text-destructive hover:underline"
                      disabled={deleteLeaveType.isPending}
                    >
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {activeTab === 'users' && (<><div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-5">
          <SearchInput
            value={search}
            onChange={setSearch}
            suggestions={searchSuggestions}
            onSelect={(val) => {
              const match = (users ?? []).find(
                (u) => u.full_name === val || u.email === val
              );
              if (match) {
                setSearch('');
                setSelectedUserDetails(match);
              }
            }}
            placeholder="Search by name, email, role, department..."
            className="w-full px-3 py-2 border rounded-lg"
          />
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value as 'ALL' | UserRole)}
            className="w-full px-3 py-2 border rounded-lg"
          >
            <option value="ALL">All roles</option>
            {roles.map((role) => (
              <option key={role} value={role}>{role}</option>
            ))}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'ALL' | 'ACTIVE' | 'INACTIVE')}
            className="w-full px-3 py-2 border rounded-lg"
          >
            <option value="ALL">All statuses</option>
            <option value="ACTIVE">Active</option>
            <option value="INACTIVE">Inactive</option>
          </select>
        </div>
        {/* Attention filter chip — surfaced when the admin clicked
            through from the dashboard Action Queue. The X button
            clears the filter (also rewrites the URL so a refresh
            doesn't bring it back). */}
        {attentionFilter !== 'NONE' && (
          <div className="mb-5 flex items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
              {attentionFilter === 'NO_MANAGER'
                ? `Showing ${filtered.length} user${filtered.length === 1 ? '' : 's'} without a manager`
                : `Showing ${filtered.length} unverified invitation${filtered.length === 1 ? '' : 's'} > 7 days old`}
              <button
                type="button"
                onClick={() => {
                  setAttentionFilter('NONE');
                  // Strip the URL param so refresh doesn't re-apply.
                  setSearchParams((prev) => {
                    const next = new URLSearchParams(prev);
                    if (next.get('status') === 'NO_MANAGER') next.delete('status');
                    next.delete('verified');
                    return next;
                  }, { replace: true });
                }}
                className="text-primary/70 hover:text-primary"
                aria-label="Clear attention filter"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </span>
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {roles.map((role) => {
            const count = (users ?? []).filter((u) => u.role === role).length;
            const isSelected = roleFilter === role && statusFilter === 'ALL';
            return (
              <button
                key={role}
                type="button"
                onClick={() => applyUserListFilter(role, 'ALL')}
                className={`bg-card border rounded-xl p-4 text-left hover:bg-muted/30 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 ${isSelected ? 'ring-2 ring-primary' : ''}`}
              >
                <p className="text-sm text-muted-foreground">{role}</p>
                <p className="text-2xl font-bold mt-1">{count}</p>
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => applyUserListFilter('ALL', 'INACTIVE')}
            className={`bg-card border rounded-xl p-4 text-left hover:bg-muted/30 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 ${roleFilter === 'ALL' && statusFilter === 'INACTIVE' ? 'ring-2 ring-primary' : ''}`}
          >
            <p className="text-sm text-muted-foreground">Inactive</p>
            <p className="text-2xl font-bold mt-1">{(users ?? []).filter((u) => !u.is_active).length}</p>
          </button>
        </div>

        {isAdminUser && (
        <div className="bg-card border rounded-xl p-4 mb-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold">Active User Management Alerts</h2>
            <span className="text-xs font-semibold rounded-full bg-red-100 text-red-700 px-2 py-0.5">
              {notificationsSummary?.route_counts?.admin ?? 0}
            </span>
          </div>

          {userManagementAlerts.length === 0 ? (
            <p className="text-sm text-muted-foreground">No active user management alerts.</p>
          ) : (
            <div className="space-y-2">
              {userManagementAlerts.map((alert) => {
                const isNoProjectAlert = alert.title.toLowerCase().includes('project access');
                return (
                  <div
                    key={alert.id}
                    className={`rounded-lg border p-3 bg-muted/20 ${isNoProjectAlert ? 'cursor-pointer hover:bg-muted/40 transition-colors' : ''}`}
                    onClick={isNoProjectAlert ? () => setShowNoProjectModal(true) : undefined}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold">{alert.title}</p>
                      <div className="flex items-center gap-2">
                        {isNoProjectAlert && (
                          <span className="text-xs text-primary font-medium">View employees →</span>
                        )}
                        <span className="text-[11px] font-semibold rounded-full bg-red-100 text-red-700 px-2 py-0.5">
                          {alert.count > 99 ? '99+' : alert.count}
                        </span>
                      </div>
                    </div>
                    <p className="text-sm text-muted-foreground mt-1">{alert.message}</p>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        )}

        {isAdminUser && (
          <div className="bg-card border rounded-xl p-4 mb-6">
            <h2 className="text-lg font-semibold mb-4">Org Chart</h2>
            <OrganizationalChart
              users={users ?? []}
              usersByManager={usersByManager}
              topLevelUsers={topLevelUsers}
              currentUserId={currentUser?.id}
            />
          </div>
        )}

        <div ref={userListSectionRef} className="surface-card overflow-hidden">
          {isAdminUser && (
            <div className="px-4 pt-3">
              <BulkSelectBar
                selectedCount={selectedUserIds.size}
                totalCount={filtered.filter((u) => u.id !== currentUser?.id).length}
                onSelectAll={selectAllUsers}
                onClearSelection={clearSelection}
                onDelete={handleBulkDelete}
                isDeleting={bulkDeleteUsers.isPending}
                itemLabel="user"
              />
            </div>
          )}
          <table className="w-full text-sm">
            <thead className="border-b border-border">
              <tr>
                {isAdminUser && (
                  <th className="w-10 px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selectedUserIds.size > 0 && filtered.filter((u) => u.id !== currentUser?.id).every((u) => selectedUserIds.has(u.id))}
                      onChange={(e) => e.target.checked ? selectAllUsers() : clearSelection()}
                      className="rounded border-gray-300"
                    />
                  </th>
                )}
                <th className="text-left px-4 py-3 font-semibold">Name</th>
                <th className="text-left px-4 py-3 font-semibold">Email</th>
                <th className="text-left px-4 py-3 font-semibold">Role</th>
                <th className="text-left px-4 py-3 font-semibold">Title</th>
                <th className="text-left px-4 py-3 font-semibold">Department</th>
                <th className="text-left px-4 py-3 font-semibold">Status</th>
                <th className="text-left px-4 py-3 font-semibold">Created</th>
                <th className="text-right px-4 py-3 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={isAdminUser ? 9 : 8} className="text-center py-10 text-muted-foreground">
                    No users found
                  </td>
                </tr>
              )}
              {filtered.map((u) => (
                <tr key={u.id} className={`h-11 hover:bg-muted transition-colors ${!u.is_active ? 'opacity-50' : ''} ${selectedUserIds.has(u.id) ? 'bg-primary/5' : ''}`}>
                  {isAdminUser && (
                    <td className="w-10 px-4 py-3">
                      {u.id !== currentUser?.id ? (
                        <input
                          type="checkbox"
                          checked={selectedUserIds.has(u.id)}
                          onChange={() => toggleUserSelection(u.id)}
                          className="rounded border-gray-300"
                        />
                      ) : (
                        <span />
                      )}
                    </td>
                  )}
                  <td className="px-4 py-3 font-medium">
                    <button
                      onClick={() => setSelectedUserDetails(u)}
                      className="text-left underline underline-offset-2 hover:text-primary"
                    >
                      {u.full_name}
                    </button>
                    {u.id === currentUser?.id && (
                      <span className="ml-2 text-[10px] text-muted-foreground border rounded-full px-1.5 py-0.5">you</span>
                    )}
                    {u.timesheet_locked && (
                      <button
                        className="ml-1 text-amber-500 hover:text-amber-700"
                        title={u.timesheet_locked_reason ?? 'Timesheet locked — click to unlock'}
                        onClick={(e) => { e.stopPropagation(); unlockUser.mutate(u.id); }}
                      >
                        🔒
                      </button>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{u.email}</td>
                  <td className="px-4 py-3">{roleBadge(u.role, u.roles)}</td>
                  <td className="px-4 py-3 text-muted-foreground">{u.title || '—'}</td>
                  <td className="px-4 py-3 text-muted-foreground">{u.department || '—'}</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => handleToggleActive(u)}
                      disabled={!isAdminUser || u.id === currentUser?.id}
                      title={u.id === currentUser?.id ? "Can't deactivate yourself" : undefined}
                      className={`inline-flex h-5 items-center rounded-full px-2 text-[11px] font-medium transition ${
                        u.is_active
                          ? 'bg-[var(--success-light)] text-[var(--success)]'
                          : 'bg-[var(--bg-surface-3)] text-[var(--text-secondary)]'
                      } disabled:cursor-not-allowed disabled:opacity-60`}
                    >
                      {u.is_active ? 'Active' : 'Inactive'}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{format(new Date(u.created_at), 'MMM d, yyyy')}</td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end" data-user-action-menu>
                      <UserActionMenu
                        isOpen={actionMenuUserId === u.id}
                        onToggle={() => setActionMenuUserId(actionMenuUserId === u.id ? null : u.id)}
                        onClose={() => setActionMenuUserId(null)}
                        canEdit={canEditUser(u)}
                        canManage={isAdminUser && u.id !== currentUser?.id}
                        isResendDisabled={u.email_verified || resendVerification.isPending}
                        resendTooltip={u.email_verified ? 'User is already verified' : 'Send a fresh verification email with a new temp password'}
                        onEdit={() => openEdit(u)}
                        onResend={() => handleResendVerification(u)}
                        onResetPassword={() => { setResetPasswordUserId(u.id); setResetPasswordValue(''); setResetPasswordError(''); }}
                        onDelete={() => setConfirmDeleteId(u.id)}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div></>)}
      </div>

      {showModal && (
        <div className="fixed inset-0 z-50 bg-[rgba(0,0,0,0.15)]">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="edit-user-modal-title"
            className="ml-auto flex h-full w-full max-w-[420px] flex-col bg-card shadow-[0_4px_16px_rgba(0,0,0,0.08)]"
          >
            <div className="flex shrink-0 items-center justify-between border-b border-border px-6 py-4">
              <h2 id="edit-user-modal-title" className="text-lg font-bold">
                {editingUser ? `Edit User · ${editingUser.full_name}` : 'New User'}
              </h2>
              <button onClick={closeModal} className="p-1.5 rounded hover:bg-muted">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 space-y-4 overflow-y-auto px-6 py-6">
                {isProjectOnlyEdit ? (
                  <div className="rounded bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
                    Managers can only update project access for employees. Updating access for <span className="font-medium text-foreground">{editingUser?.full_name}</span>.
                  </div>
                ) : (
                  <>
                    <div>
                      <label className="block text-sm font-medium mb-1">
                        User type
                        <span className="ml-1 text-destructive" aria-hidden>*</span>
                      </label>
                      <div className="grid grid-cols-2 gap-2">
                        {(['internal', 'external'] as const).map((opt) => {
                          const checked = form.audience === opt;
                          const label = opt === 'internal' ? 'Internal' : 'External';
                          return (
                            <button
                              key={opt}
                              type="button"
                              onClick={() => setForm((f) => ({ ...f, audience: opt }))}
                              className={cn(
                                'rounded-lg border px-3 py-2 text-sm font-semibold transition',
                                checked
                                  ? 'border-primary bg-primary/10 ring-1 ring-primary/40'
                                  : 'border-border hover:bg-muted/40',
                              )}
                              aria-pressed={checked}
                            >
                              {label}
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <label className="block text-sm font-medium mb-1">
                        Full Name
                        <span className="ml-1 text-destructive" aria-hidden>*</span>
                      </label>
                      <input
                        required
                        value={form.full_name}
                        onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
                        className="w-full px-3 py-2 border rounded"
                        placeholder="Jane Smith"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium mb-1">Email</label>
                      <input
                        type="email"
                        value={form.email}
                        onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                        className="w-full px-3 py-2 border rounded"
                        placeholder="jane@example.com"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium mb-1">Username</label>
                      <input
                        type="text"
                        value={form.username}
                        onChange={(e) => setForm((f) => ({ ...f, username: e.target.value.toLowerCase() }))}
                        className="w-full px-3 py-2 border rounded"
                        placeholder="jane.smith"
                        minLength={3}
                      />
                    </div>
                    {form.audience === 'internal' && (<>
                    <div>
                      <label className="block text-sm font-medium mb-1">Role</label>
                      <select
                        value={form.role}
                        onChange={(e) => {
                          const nextRole = e.target.value as UserRole;
                          setForm((f) => {
                            const nextAllowedSupervisorRoles = getAllowedSupervisorRoles(nextRole);
                            const nextManagerId =
                              f.manager_id &&
                              (users ?? []).some(
                                (candidate) =>
                                  candidate.id === f.manager_id &&
                                  candidate.id !== editingUser?.id &&
                                  nextAllowedSupervisorRoles.includes(candidate.role)
                              )
                                ? f.manager_id
                                : null;

                            // Drop the new primary from additional_roles
                            // so the combined list never duplicates.
                            const nextAdditional = f.additional_roles.filter((r) => r !== nextRole);

                            return {
                              ...f,
                              role: nextRole,
                              additional_roles: nextAdditional,
                              manager_id: nextManagerId,
                              project_ids: nextRole === 'EMPLOYEE' ? f.project_ids : [],
                            };
                          });
                        }}
                        className="w-full px-3 py-2 border rounded"
                      >
                        {roles.map((r) => (
                          <option key={r} value={r}>{r}</option>
                        ))}
                      </select>
                    </div>
                    {/* Additional roles. Lets the admin grant a single
                        human access to multiple portals (e.g., admin
                        who is also a manager). Hidden for primary
                        roles where it's not meaningful: an EMPLOYEE
                        rarely needs another portal, and PLATFORM_ADMIN
                        is its own identity. */}
                    {form.role !== 'EMPLOYEE' && form.role !== 'PLATFORM_ADMIN' && (
                      <div>
                        <label className="block text-sm font-medium mb-1">
                          Additional portals
                          <span className="ml-2 text-xs font-normal text-muted-foreground">
                            access to other roles for the same login
                          </span>
                        </label>
                        <div className="space-y-1.5 rounded border px-3 py-2">
                          {ADDITIONAL_ROLE_OPTIONS.filter((r) => r !== form.role).map((r) => {
                            const checked = form.additional_roles.includes(r);
                            return (
                              <label key={r} className="flex items-center gap-2 text-sm">
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={(e) => {
                                    setForm((f) => {
                                      const next = e.target.checked
                                        ? Array.from(new Set([...f.additional_roles, r]))
                                        : f.additional_roles.filter((existing) => existing !== r);
                                      return { ...f, additional_roles: next };
                                    });
                                  }}
                                  className="h-4 w-4"
                                />
                                <span>{r}</span>
                              </label>
                            );
                          })}
                          <p className="text-[11px] text-muted-foreground pt-1">
                            When more than one portal is checked, the user picks one at login and can switch via the topbar.
                          </p>
                        </div>
                      </div>
                    )}
                    {(form.role === 'MANAGER' || form.role === 'EMPLOYEE') && (
                      <div>
                        <label className="block text-sm font-medium mb-1">Title</label>
                        <input
                          required
                          value={form.title}
                          onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                          className="w-full px-3 py-2 border rounded"
                          placeholder={form.role === 'MANAGER' ? 'Manager' : 'Senior Software Engineer'}
                        />
                      </div>
                    )}
                    {(form.role === 'MANAGER' || form.role === 'EMPLOYEE' || form.role === 'ADMIN') && (
                      <div>
                        <label className="block text-sm font-medium mb-1">Department</label>
                        <div className="flex gap-2">
                          <select
                            required={form.role === 'MANAGER'}
                            value={form.department}
                            onChange={(e) => {
                              const v = e.target.value;
                              if (v === '__new__') {
                                const name = window.prompt('New department name')?.trim();
                                if (!name) return;
                                createDepartment.mutate(name, {
                                  onSuccess: (created) => setForm((f) => ({ ...f, department: created.name })),
                                  onError: () => alert('Failed to create department (it may already exist).'),
                                });
                                return;
                              }
                              setForm((f) => ({ ...f, department: v }));
                            }}
                            className="flex-1 px-3 py-2 border rounded"
                          >
                            <option value="">{form.role === 'MANAGER' ? 'Select a department' : '— No department —'}</option>
                            {departments.map((d) => (
                              <option key={d.id} value={d.name}>{d.name}</option>
                            ))}
                            {form.department && !departments.some((d) => d.name === form.department) && (
                              <option value={form.department}>{form.department} (legacy)</option>
                            )}
                            <option value="__new__">+ Add new department…</option>
                          </select>
                        </div>
                      </div>
                    )}
                    <div>
                      <label className="block text-sm font-medium mb-1">Reports To</label>
                      <select
                        value={form.manager_id ?? ''}
                        onChange={(e) => setForm((f) => ({ ...f, manager_id: e.target.value ? Number(e.target.value) : null }))}
                        className="w-full px-3 py-2 border rounded"
                      >
                        <option value="">Unassigned</option>
                        {supervisors
                          .filter((supervisor) => supervisor.id !== editingUser?.id)
                          .map((supervisor) => (
                            <option key={supervisor.id} value={supervisor.id}>{supervisor.full_name}</option>
                          ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium mb-1">Default Client</label>
                      <select
                        value={form.default_client_id ?? ''}
                        onChange={(e) => setForm((f) => ({ ...f, default_client_id: e.target.value ? Number(e.target.value) : null }))}
                        className="w-full px-3 py-2 border rounded"
                      >
                        <option value="">— No default —</option>
                        {clientsList.map((client: { id: number; name: string }) => (
                          <option key={client.id} value={client.id}>{client.name}</option>
                        ))}
                      </select>
                      <p className="mt-1 text-xs text-muted-foreground">Optional. When set, incoming timesheets resolved to this user auto-route to this client.</p>
                    </div>
                    </>)}
                  </>
                )}
                {!isProjectOnlyEdit && form.audience === 'internal' && (form.role === 'EMPLOYEE' || isProjectOnlyEdit) && (
                  <div>
                    <label className="block text-sm font-medium mb-2">Project Access</label>
                    <div className="max-h-44 overflow-y-auto rounded border p-3 space-y-2 bg-muted/10">
                      {activeProjects.length === 0 && (
                        <p className="text-sm text-muted-foreground">No active projects available.</p>
                      )}
                      {activeProjects.map((project: Project) => (
                        <label key={project.id} className="flex items-start gap-3 text-sm">
                          <input
                            type="checkbox"
                            checked={form.project_ids.includes(project.id)}
                            onChange={() => handleProjectToggle(project.id)}
                            disabled={!canManageEmployeeProjects}
                            className="mt-0.5 rounded"
                          />
                          <span>
                            <span className="font-medium text-foreground">{project.name}</span>
                            {project.client?.name && (
                              <span className="block text-xs text-muted-foreground">{project.client.name}</span>
                            )}
                          </span>
                        </label>
                      ))}
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                      Selected projects control project visibility for this report.
                    </p>
                  </div>
                )}
                {!isProjectOnlyEdit && (
                  <div className={cn(
                    'grid gap-3',
                    form.audience === 'internal' ? 'md:grid-cols-2' : 'md:grid-cols-1',
                  )}>
                    <label className="flex items-center gap-2">
                      <input
                        id="is_active"
                        type="checkbox"
                        checked={form.is_active}
                        onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
                        className="rounded"
                      />
                      <span className="text-sm font-medium">Active account</span>
                    </label>
                    {form.audience === 'internal' && (
                    <label className="flex items-center gap-2">
                      <input
                        id="can_review"
                        type="checkbox"
                        checked={form.can_review}
                        onChange={(e) => setForm((f) => ({ ...f, can_review: e.target.checked }))}
                        className="rounded"
                      />
                      <span className="text-sm font-medium">Reviewer access</span>
                    </label>
                    )}
                    {/* Legacy "External user" checkbox is intentionally
                        removed — the Internal/External chip at the top
                        of the form is the single source of truth. */}
                    <label className="hidden">
                      <input
                        id="is_external_legacy"
                        type="checkbox"
                        checked={false}
                        readOnly
                      />
                      <span className="text-sm font-medium">External user</span>
                    </label>
                  </div>
                )}
              </div>

              <div className="shrink-0 border-t px-6 py-4">
                {formError && (
                  <p className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-600">{formError}</p>
                )}

                <div className="flex gap-3">
                  <button
                    type="submit"
                    disabled={createUser.isPending || updateUser.isPending}
                    className="flex-1 px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
                  >
                    {createUser.isPending || updateUser.isPending ? 'Saving...' : editingUser ? (isProjectOnlyEdit ? 'Save Project Access' : 'Save Changes') : 'Create User'}
                  </button>
                  <button
                    type="button"
                    onClick={closeModal}
                    className="flex-1 px-4 py-2 bg-muted rounded hover:bg-muted/90"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}

      {isAdminUser && confirmDeleteId !== null && (() => {
        const userToDelete = (users ?? []).find((u) => u.id === confirmDeleteId);
        return (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 px-4">
          <div className="bg-card rounded-xl shadow-2xl w-full max-w-sm p-6">
            <h2 className="text-lg font-bold mb-2">Delete User</h2>
            <p className="text-sm text-muted-foreground mb-1">
              Are you sure you want to permanently delete:
            </p>
            <p className="font-semibold text-foreground mb-1">{userToDelete?.full_name}</p>
            <p className="text-xs text-muted-foreground mb-5">{userToDelete?.email}</p>
            <p className="text-xs text-red-600 mb-5">This action cannot be undone.</p>
            <div className="flex gap-3">
              <button
                onClick={() => handleDelete(confirmDeleteId)}
                disabled={deleteUser.isPending}
                className="flex-1 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
              >
                {deleteUser.isPending ? 'Deleting...' : 'Delete'}
              </button>
              <button
                onClick={() => setConfirmDeleteId(null)}
                className="flex-1 px-4 py-2 bg-muted rounded hover:bg-muted/90"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
        );
      })()}

      {/* Reset password modal */}
      {resetPasswordUserId !== null && (() => {
        const targetUser = (users ?? []).find((u) => u.id === resetPasswordUserId);
        return (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 px-4">
            <div className="bg-card rounded-xl shadow-2xl w-full max-w-sm p-6">
              <h2 className="text-lg font-bold mb-2">Reset Password</h2>
              <p className="text-sm text-muted-foreground mb-1">
                Set a new password for:
              </p>
              <p className="font-semibold text-foreground mb-1">{targetUser?.full_name}</p>
              <p className="text-xs text-muted-foreground mb-4">{targetUser?.email}</p>
              <input
                type="password"
                value={resetPasswordValue}
                onChange={(e) => setResetPasswordValue(e.target.value)}
                placeholder="New password (min 8 characters)"
                className="field-input mb-2"
                autoFocus
                onKeyDown={(e) => { if (e.key === 'Enter') handleResetPassword(); }}
              />
              <p className="text-xs text-muted-foreground mb-3">User will be prompted to change it on next login.</p>
              {resetPasswordError && (
                <p className="text-xs text-destructive mb-3">{resetPasswordError}</p>
              )}
              <div className="flex gap-3">
                <button
                  onClick={handleResetPassword}
                  disabled={resetPassword.isPending || !resetPasswordValue.trim()}
                  className="flex-1 px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
                >
                  {resetPassword.isPending ? 'Resetting...' : 'Reset Password'}
                </button>
                <button
                  onClick={() => { setResetPasswordUserId(null); setResetPasswordValue(''); setResetPasswordError(''); }}
                  className="flex-1 px-4 py-2 bg-muted rounded hover:bg-muted/90"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Post-create confirmation. Copy depends on whether the user
          is external, whether they have a real email on file, and
          whether the backend queued a verification message. */}
      {createdUserSummary && (() => {
        const { fullName, email, isExternal, verificationEmailSent } = createdUserSummary;
        const isPlaceholderEmail = !email || email.toLowerCase().endsWith('@local.invalid');
        let body: string;
        if (isExternal) {
          body = `${fullName} created as external. Record-only, no login.`;
        } else if (verificationEmailSent && !isPlaceholderEmail) {
          body = `Verification email sent to ${email}.`;
        } else {
          body = `${fullName} created. Add an email later to send a verification link.`;
        }
        return (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 px-4">
            <div className="bg-card rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
              <h2 className="text-lg font-semibold text-foreground">User created</h2>
              <p className="text-sm text-muted-foreground">{body}</p>
              <div className="flex justify-end">
                <button
                  className="action-button"
                  onClick={() => setCreatedUserSummary(null)}
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        );
      })()}

      {showNoProjectModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 px-4">
          <div className="bg-card rounded-xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <div>
                <h2 className="text-lg font-bold">Employees Without Project Access</h2>
                <p className="text-sm text-muted-foreground mt-0.5">{employeesWithoutProjects.length} active employees with no projects assigned</p>
              </div>
              <button onClick={() => setShowNoProjectModal(false)} className="p-1.5 rounded hover:bg-muted">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="overflow-y-auto flex-1">
              {employeesWithoutProjects.length === 0 ? (
                <p className="text-sm text-muted-foreground p-6">All employees have project access assigned.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 border-b sticky top-0">
                    <tr>
                      <th className="text-left px-4 py-3 font-semibold">Name</th>
                      <th className="text-left px-4 py-3 font-semibold">Email</th>
                      <th className="text-left px-4 py-3 font-semibold">Department</th>
                      <th className="text-right px-4 py-3 font-semibold">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {employeesWithoutProjects.map((u) => (
                      <tr key={u.id} className="hover:bg-muted/10">
                        <td className="px-4 py-3 font-medium">{u.full_name}</td>
                        <td className="px-4 py-3 text-muted-foreground">{u.email}</td>
                        <td className="px-4 py-3 text-muted-foreground">{u.department || '—'}</td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() => {
                              setShowNoProjectModal(false);
                              openEdit(u);
                            }}
                            className="flex items-center gap-1.5 ml-auto px-3 py-1.5 bg-primary text-primary-foreground rounded-lg text-xs hover:bg-primary/90"
                          >
                            <Pencil className="w-3 h-3" />
                            Assign Projects
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {selectedUserDetails && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 px-4">
          <div className="bg-card rounded-xl shadow-2xl w-full max-w-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h2 className="text-lg font-bold">User Details</h2>
              <button onClick={() => setSelectedUserDetails(null)} className="p-1.5 rounded hover:bg-muted">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-5">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-muted-foreground">Full Name</p>
                  <p className="font-medium">{selectedUserDetails.full_name}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Email</p>
                  <p className="font-medium">{selectedUserDetails.email}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Role</p>
                  <div className="mt-1">{roleBadge(selectedUserDetails.role, selectedUserDetails.roles)}</div>
                </div>
                <div>
                  <p className="text-muted-foreground">Status</p>
                  <p className="font-medium">{selectedUserDetails.is_active ? 'Active' : 'Inactive'}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Title</p>
                  <p className="font-medium">{selectedUserDetails.title || '—'}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Department</p>
                  <p className="font-medium">{selectedUserDetails.department || '—'}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Reports To</p>
                  <p className="font-medium">{getManagerDisplayName(selectedUserDetails.manager_id)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Created</p>
                  <p className="font-medium">{format(new Date(selectedUserDetails.created_at), 'MMM d, yyyy')}</p>
                </div>
              </div>

              <div>
                <h3 className="font-semibold mb-2">Project & Client Access</h3>
                {getUserProjectDetails(selectedUserDetails).length === 0 ? (
                  <p className="text-sm text-muted-foreground">No project access assigned.</p>
                ) : (
                  <div className="space-y-2">
                    {getUserProjectDetails(selectedUserDetails).map((project: Project) => (
                      <div key={project.id} className="rounded-lg border px-3 py-2 text-sm">
                        <p className="font-medium">{project.name}</p>
                        <p className="text-muted-foreground">Client: {project.client?.name || '—'}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {canEditUser(selectedUserDetails) && (
              <div className="px-6 pb-6">
                <button
                  onClick={() => {
                    const u = selectedUserDetails;
                    setSelectedUserDetails(null);
                    openEdit(u);
                  }}
                  className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
                >
                  <Pencil className="w-4 h-4" />
                  Edit User
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
