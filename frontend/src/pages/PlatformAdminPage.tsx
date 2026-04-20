import React, { useState, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { format } from 'date-fns';
import { useSearchParams } from 'react-router-dom';
import {
  PlusCircle, Pencil, X, Building2, CheckCircle, XCircle,
  PauseCircle, ShieldAlert, Trash2, UserCog, ChevronDown, ChevronRight, Bot, KeyRound,
  MoreVertical, MailCheck,
} from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { tenantsAPI } from '@/api';
import { useUsers, useCreateUser, useUpdateUser, useDeleteUser, useResetUserPassword, useResendVerification } from '@/hooks';
import { ServiceToken, ServiceTokenCreated, Tenant, TenantStatus, User, UserRole } from '@/types';

// ─── Helpers ───────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<TenantStatus, { label: string; classes: string; icon: React.ReactNode }> = {
  active:    { label: 'Active',    classes: 'bg-emerald-100 text-emerald-800', icon: <CheckCircle className="w-3 h-3" /> },
  inactive:  { label: 'Inactive',  classes: 'bg-slate-100 text-slate-700',    icon: <XCircle className="w-3 h-3" /> },
  suspended: { label: 'Suspended', classes: 'bg-red-100 text-red-700',        icon: <PauseCircle className="w-3 h-3" /> },
};

const StatusBadge: React.FC<{ status: TenantStatus }> = ({ status }) => {
  const cfg = STATUS_CONFIG[status];
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.classes}`}>
      {cfg.icon}{cfg.label}
    </span>
  );
};

const slugify = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const apiError = (e: unknown) =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Something went wrong';

// ─── Form types ────────────────────────────────────────────────────────────

type TenantFormState = { name: string; slug: string; status: TenantStatus; ingestion_enabled: boolean; max_mailboxes: string };
const emptyTenantForm = (): TenantFormState => ({ name: '', slug: '', status: 'active', ingestion_enabled: false, max_mailboxes: '1' });

type AdminFormState = { full_name: string; email: string; username: string; password: string };
const emptyAdminForm = (): AdminFormState => ({ full_name: '', email: '', username: '', password: 'password' });

type AdminEditFormState = { full_name: string; email: string; username: string; is_active: boolean };
const emptyAdminEditForm = (): AdminEditFormState => ({ full_name: '', email: '', username: '', is_active: true });

type AdminResetPasswordState = { userId: number; value: string; error: string } | null;

type TokenFormState = { name: string; issuer: string };
const emptyTokenForm = (): TokenFormState => ({ name: '', issuer: '' });

// ─── Admin row action menu (flips upward when near container bottom) ──────

type AdminActionMenuProps = {
  isOpen: boolean;
  onToggle: () => void;
  onClose: () => void;
  canResend: boolean;
  resendTooltip: string;
  adminLabel: string;
  onEdit: () => void;
  onResend: () => void;
  onResetPassword: () => void;
  onDelete: () => void;
};

const AdminActionMenu: React.FC<AdminActionMenuProps> = ({
  isOpen, onToggle, onClose, canResend, resendTooltip, adminLabel,
  onEdit, onResend, onResetPassword, onDelete,
}) => {
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  // Dropdown is rendered into document.body via a portal so parent containers
  // with overflow-hidden (e.g. the tenant panel) don't clip it. We compute
  // absolute coords from the trigger button each time the menu opens and on
  // window resize.
  const [position, setPosition] = React.useState<{ top: number; left: number; openUp: boolean } | null>(null);

  const recompute = React.useCallback(() => {
    if (!buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    const menuHeight = 200;
    const menuWidth = 180;
    const spaceBelow = window.innerHeight - rect.bottom;
    const openUp = spaceBelow < menuHeight && rect.top > menuHeight;
    const top = openUp ? rect.top - menuHeight - 4 : rect.bottom + 4;
    // Align right edge of menu with right edge of button.
    const left = Math.max(8, rect.right - menuWidth);
    setPosition({ top, left, openUp });
  }, []);

  React.useEffect(() => {
    if (!isOpen) {
      setPosition(null);
      return;
    }
    recompute();
    const onResize = () => recompute();
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onResize, true);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onResize, true);
    };
  }, [isOpen, recompute]);

  return (
    <div className="relative inline-block" data-admin-action-menu>
      <button
        ref={buttonRef}
        onClick={onToggle}
        className="p-1 rounded hover:bg-slate-100 text-slate-500"
        title="Actions"
        aria-label={`Actions for ${adminLabel}`}
      >
        <MoreVertical className="w-4 h-4" />
      </button>
      {isOpen && position && createPortal(
        <div
          data-admin-action-menu
          style={{ position: 'fixed', top: position.top, left: position.left, width: 180 }}
          className="z-50 rounded-lg border border-slate-200 bg-white shadow-lg py-1"
        >
          <button
            onClick={() => { onClose(); onEdit(); }}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 text-left"
          >
            <Pencil className="w-3.5 h-3.5" /> Edit
          </button>
          <button
            onClick={() => { if (!canResend) return; onClose(); onResend(); }}
            disabled={!canResend}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 text-left disabled:opacity-40 disabled:cursor-not-allowed"
            title={resendTooltip}
          >
            <MailCheck className="w-3.5 h-3.5" /> Resend verification
          </button>
          <button
            onClick={() => { onClose(); onResetPassword(); }}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 text-left"
          >
            <KeyRound className="w-3.5 h-3.5" /> Reset password
          </button>
          <button
            onClick={() => { onClose(); onDelete(); }}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50 text-left"
          >
            <Trash2 className="w-3.5 h-3.5" /> Delete
          </button>
        </div>,
        document.body,
      )}
    </div>
  );
};

// ─── Component ─────────────────────────────────────────────────────────────

export const PlatformAdminPage: React.FC = () => {
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();

  // ── Data ─────────────────────────────────────────────────────────────────
  const { data: tenants = [], isLoading: tenantsLoading } = useQuery({
    queryKey: ['tenants'],
    queryFn: () => tenantsAPI.list().then((r) => r.data),
  });

  const { data: allUsers = [], isLoading: usersLoading } = useUsers();

  const adminsByTenant = useMemo(() => {
    const map: Record<number, typeof allUsers> = {};
    allUsers
      .filter((u) => u.role === 'ADMIN' && u.tenant_id != null)
      .forEach((u) => {
        map[u.tenant_id!] = [...(map[u.tenant_id!] ?? []), u];
      });
    return map;
  }, [allUsers]);

  const tenantUserCount = useMemo(
    () => allUsers.filter((u) => u.tenant_id != null).length,
    [allUsers],
  );

  const totalAdmins = useMemo(
    () => allUsers.filter((u) => u.role === 'ADMIN' && u.tenant_id != null).length,
    [allUsers],
  );

  // ── Tenant mutations ──────────────────────────────────────────────────────
  const createTenantMutation = useMutation({
    mutationFn: (d: { name: string; slug: string }) => tenantsAPI.create(d).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tenants'] }); qc.invalidateQueries({ queryKey: ['dashboard'] }); closeTenantModal(); },
    onError: (e: unknown) => setTenantFormError(apiError(e)),
  });
  const updateTenantMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<Omit<TenantFormState, 'max_mailboxes'>> & { max_mailboxes?: number | null } }) =>
      tenantsAPI.update(id, data).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tenants'] }); qc.invalidateQueries({ queryKey: ['dashboard'] }); closeTenantModal(); },
    onError: (e: unknown) => setTenantFormError(apiError(e)),
  });

  const updateUserMutation = useUpdateUser();
  const createUserMutation = useCreateUser();
  const deleteUserMutation = useDeleteUser();

  const [provisioningTenantId, setProvisioningTenantId] = useState<number | null>(null);
  const provisionSystemUserMutation = useMutation({
    mutationFn: (tenantId: number) => tenantsAPI.provisionSystemUser(tenantId).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['users'] }); setProvisioningTenantId(null); },
    onError: () => setProvisioningTenantId(null),
  });

  // ── Tenant expand/edit state ──────────────────────────────────────────────
  const [expandedTenantId, setExpandedTenantId] = useState<number | null>(null);
  const [editingTenant, setEditingTenant] = useState<Tenant | null>(null);
  const [showCreateTenant, setShowCreateTenant] = useState(false);
  const [tenantForm, setTenantForm] = useState<TenantFormState>(emptyTenantForm());
  const [tenantFormError, setTenantFormError] = useState('');

  const toggleExpand = (id: number) =>
    setExpandedTenantId((prev) => (prev === id ? null : id));

  const openCreateTenant = () => { setTenantForm(emptyTenantForm()); setTenantFormError(''); setShowCreateTenant(true); };
  const openEditTenant = (e: React.MouseEvent, t: Tenant) => {
    e.stopPropagation();
    setTenantForm({
      name: t.name,
      slug: t.slug,
      status: t.status,
      ingestion_enabled: t.ingestion_enabled,
      max_mailboxes: t.max_mailboxes == null ? '' : String(t.max_mailboxes),
    });
    setTenantFormError('');
    setEditingTenant(t);
  };
  const closeTenantModal = () => { setShowCreateTenant(false); setEditingTenant(null); setTenantForm(emptyTenantForm()); setTenantFormError(''); };

  const handleTenantSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setTenantFormError('');
    if (!tenantForm.name.trim() || !tenantForm.slug.trim()) { setTenantFormError('Name and slug are required'); return; }
    if (!/^[a-z0-9-]+$/.test(tenantForm.slug)) { setTenantFormError('Slug must be lowercase letters, numbers, hyphens only'); return; }
    if (editingTenant) {
      const trimmed = tenantForm.max_mailboxes.trim();
      const maxMailboxes = trimmed === '' ? null : Math.max(0, parseInt(trimmed, 10) || 0);
      // Only send max_mailboxes when ingestion is on; it's meaningless otherwise.
      const { max_mailboxes: _drop, ...rest } = tenantForm;
      updateTenantMutation.mutate({
        id: editingTenant.id,
        data: tenantForm.ingestion_enabled ? { ...rest, max_mailboxes: maxMailboxes } : rest,
      });
    } else {
      createTenantMutation.mutate({ name: tenantForm.name.trim(), slug: tenantForm.slug.trim() });
    }
  };

  // ── Add admin state ───────────────────────────────────────────────────────
  const [addAdminForTenantId, setAddAdminForTenantId] = useState<number | null>(null);
  const [adminForm, setAdminForm] = useState<AdminFormState>(emptyAdminForm());
  const [adminFormError, setAdminFormError] = useState('');
  const [confirmDeleteUserId, setConfirmDeleteUserId] = useState<number | null>(null);

  // ── Edit admin state ──────────────────────────────────────────────────────
  const [editingAdmin, setEditingAdmin] = useState<User | null>(null);
  const [editAdminForm, setEditAdminForm] = useState<AdminEditFormState>(emptyAdminEditForm());
  const [editAdminError, setEditAdminError] = useState('');
  const [adminActionMenuId, setAdminActionMenuId] = useState<number | null>(null);
  const [adminResetPassword, setAdminResetPassword] = useState<AdminResetPasswordState>(null);
  const resetUserPassword = useResetUserPassword();
  const resendVerification = useResendVerification();

  const openEditAdmin = (admin: User) => {
    setEditingAdmin(admin);
    setEditAdminForm({
      full_name: admin.full_name,
      email: admin.email,
      username: admin.username ?? '',
      is_active: admin.is_active,
    });
    setEditAdminError('');
    setAdminActionMenuId(null);
  };
  const closeEditAdmin = () => {
    setEditingAdmin(null);
    setEditAdminForm(emptyAdminEditForm());
    setEditAdminError('');
  };
  const handleEditAdminSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingAdmin) return;
    setEditAdminError('');
    const full_name = editAdminForm.full_name.trim();
    const email = editAdminForm.email.trim().toLowerCase();
    const username = editAdminForm.username.trim().toLowerCase();
    if (!full_name || !email || !username) {
      setEditAdminError('Name, email, and username are required.');
      return;
    }
    if (username.length < 3) {
      setEditAdminError('Username must be at least 3 characters.');
      return;
    }
    try {
      await updateUserMutation.mutateAsync({
        id: editingAdmin.id,
        data: { full_name, email, username, is_active: editAdminForm.is_active },
      });
      closeEditAdmin();
    } catch (err) {
      setEditAdminError(apiError(err));
    }
  };

  const handleResendAdminVerification = async (admin: User) => {
    setAdminActionMenuId(null);
    try {
      await resendVerification.mutateAsync(admin.id);
    } catch {
      // Toast-less page — fall back to a simple alert so it isn't silent.
      window.alert('Could not resend verification. Please try again.');
    }
  };

  const handleResetAdminPasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!adminResetPassword) return;
    const value = adminResetPassword.value;
    if (value.length < 8) {
      setAdminResetPassword({ ...adminResetPassword, error: 'Password must be at least 8 characters.' });
      return;
    }
    try {
      await resetUserPassword.mutateAsync({ id: adminResetPassword.userId, newPassword: value });
      setAdminResetPassword(null);
    } catch (err) {
      setAdminResetPassword({ ...adminResetPassword, error: apiError(err) });
    }
  };

  // Close action menu on outside click
  React.useEffect(() => {
    if (adminActionMenuId === null) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target?.closest('[data-admin-action-menu]')) setAdminActionMenuId(null);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [adminActionMenuId]);
  const highlightedAdminUserId = useMemo(() => {
    const raw = searchParams.get('adminUserId');
    const parsed = raw ? Number(raw) : NaN;
    return Number.isFinite(parsed) ? parsed : null;
  }, [searchParams]);

  const openAddAdmin = (e: React.MouseEvent, tenantId: number) => {
    e.stopPropagation();
    setAdminForm(emptyAdminForm());
    setAdminFormError('');
    setAddAdminForTenantId(tenantId);
    setExpandedTenantId(tenantId);
  };
  const closeAdminModal = () => { setAddAdminForTenantId(null); setAdminForm(emptyAdminForm()); setAdminFormError(''); };

  const handleAdminSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setAdminFormError('');
    if (!adminForm.full_name.trim() || !adminForm.email.trim() || !adminForm.username.trim()) {
      setAdminFormError('All fields are required'); return;
    }
    createUserMutation.mutate(
      {
        full_name: adminForm.full_name, email: adminForm.email, username: adminForm.username,
        role: 'ADMIN' as UserRole, tenant_id: addAdminForTenantId!, password: adminForm.password,
      },
      { onSuccess: closeAdminModal, onError: (e) => setAdminFormError(apiError(e)) },
    );
  };

  // ── Service token state ───────────────────────────────────────────────────
  const [issueTokenForTenantId, setIssueTokenForTenantId] = useState<number | null>(null);
  const [tokenForm, setTokenForm] = useState<TokenFormState>(emptyTokenForm());
  const [tokenFormError, setTokenFormError] = useState('');
  const [issuedToken, setIssuedToken] = useState<ServiceTokenCreated | null>(null);
  const [copiedToken, setCopiedToken] = useState(false);
  const [confirmRevokeToken, setConfirmRevokeToken] = useState<{ tenantId: number; token: ServiceToken } | null>(null);

  const { data: serviceTokens = [], isLoading: tokensLoading, isError: tokensError, refetch: retryTokens } = useQuery({
    queryKey: ['service-tokens', expandedTenantId],
    queryFn: () => tenantsAPI.getServiceTokens(expandedTenantId!).then((r) => r.data),
    enabled: expandedTenantId != null,
  });

  const issueTokenMutation = useMutation({
    mutationFn: ({ tenantId, body }: { tenantId: number; body: { name: string; issuer: string } }) =>
      tenantsAPI.createServiceToken(tenantId, body).then((r) => r.data),
    onSuccess: (created) => {
      setIssuedToken(created);
    },
    onError: (e: unknown) => setTokenFormError(apiError(e)),
  });

  const revokeTokenMutation = useMutation({
    mutationFn: ({ tenantId, tokenId }: { tenantId: number; tokenId: number }) =>
      tenantsAPI.revokeServiceToken(tenantId, tokenId),
    onSuccess: (_, { tenantId }) => {
      qc.invalidateQueries({ queryKey: ['service-tokens', tenantId] });
      setConfirmRevokeToken(null);
    },
  });

  const openIssueToken = (e: React.MouseEvent, tenantId: number) => {
    e.stopPropagation();
    setTokenForm(emptyTokenForm());
    setTokenFormError('');
    setIssuedToken(null);
    setIssueTokenForTenantId(tenantId);
  };
  const closeTokenModal = () => {
    if (issuedToken) {
      qc.invalidateQueries({ queryKey: ['service-tokens', issueTokenForTenantId] });
    }
    setIssueTokenForTenantId(null);
    setTokenForm(emptyTokenForm());
    setTokenFormError('');
    setIssuedToken(null);
    setCopiedToken(false);
  };
  const handleTokenSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setTokenFormError('');
    if (!tokenForm.name.trim() || !tokenForm.issuer.trim()) {
      setTokenFormError('Both fields are required');
      return;
    }
    issueTokenMutation.mutate({ tenantId: issueTokenForTenantId!, body: { name: tokenForm.name.trim(), issuer: tokenForm.issuer.trim() } });
  };

  const isTenantPending = createTenantMutation.isPending || updateTenantMutation.isPending;
  const isTenantModalOpen = showCreateTenant || !!editingTenant;

  React.useEffect(() => {
    const rawTenantId = searchParams.get('tenantId');
    const parsedTenantId = rawTenantId ? Number(rawTenantId) : NaN;
    if (!Number.isFinite(parsedTenantId)) {
      return;
    }

    setExpandedTenantId(parsedTenantId);
    requestAnimationFrame(() => {
      const tenantRow = document.getElementById(`tenant-${parsedTenantId}`);
      tenantRow?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }, [searchParams]);

  if (tenantsLoading || usersLoading) {
    return <div className="flex min-h-screen items-center justify-center"><p className="text-slate-500">Loading…</p></div>;
  }

  return (
    <div>
      <div className="p-1">
        <div className="max-w-5xl mx-auto">

          {/* Page header */}
          <div className="flex items-center gap-3 mb-6">
            <ShieldAlert className="w-6 h-6 text-primary" />
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Platform Administration</h1>
              <p className="text-sm text-slate-500">Manage tenants and their admin contacts</p>
            </div>
          </div>

          {/* Summary cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Tenants</p>
              <p className="mt-1 text-2xl font-bold text-slate-900">{tenants.length}</p>
            </div>
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Active</p>
              <p className="mt-1 text-2xl font-bold text-emerald-600">{tenants.filter((t) => t.status === 'active').length}</p>
            </div>
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Tenant Users</p>
              <p className="mt-1 text-2xl font-bold text-slate-900">{tenantUserCount}</p>
            </div>
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Admin Contacts</p>
              <p className="mt-1 text-2xl font-bold text-blue-600">{totalAdmins}</p>
            </div>
          </div>

          {/* Tenant table */}
          <div className="flex justify-end mb-4">
            <button
              onClick={openCreateTenant}
              className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              <PlusCircle className="w-4 h-4" />New Tenant
            </button>
          </div>

          <div className="rounded-xl border bg-white shadow-sm overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b text-left">
                <tr>
                  <th className="w-8 px-3 py-3"></th>
                  <th className="px-4 py-3 font-semibold text-slate-700">Name</th>
                  <th className="px-4 py-3 font-semibold text-slate-700">Slug</th>
                  <th className="px-4 py-3 font-semibold text-slate-700">Status</th>
                  <th className="px-4 py-3 font-semibold text-slate-700">Admins</th>
                  <th className="px-4 py-3 font-semibold text-slate-700">Created</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {tenants.length === 0 && (
                  <tr><td colSpan={7} className="px-4 py-8 text-center text-slate-400">No tenants yet</td></tr>
                )}
                {tenants.map((t) => {
                  const admins = adminsByTenant[t.id] ?? [];
                  const isExpanded = expandedTenantId === t.id;

                  return (
                    <React.Fragment key={t.id}>
                      {/* Tenant row */}
                      <tr
                        id={`tenant-${t.id}`}
                        onClick={() => toggleExpand(t.id)}
                        className={`border-t cursor-pointer transition ${isExpanded ? 'bg-slate-50' : 'hover:bg-slate-50'}`}
                      >
                        <td className="px-3 py-3 text-slate-400">
                          {isExpanded
                            ? <ChevronDown className="w-4 h-4" />
                            : <ChevronRight className="w-4 h-4" />}
                        </td>
                        <td className="px-4 py-3 font-medium text-slate-900">{t.name}</td>
                        <td className="px-4 py-3 font-mono text-xs text-slate-500">{t.slug}</td>
                        <td className="px-4 py-3">
                          <div className="flex flex-col gap-2">
                            <StatusBadge status={t.status} />
                            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${t.ingestion_enabled ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-500'}`}>
                              {t.ingestion_enabled ? 'Ingestion on' : 'Ingestion off'}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex items-center gap-1 text-sm font-medium ${admins.length === 0 ? 'text-amber-600' : 'text-slate-700'}`}>
                            <UserCog className="w-3.5 h-3.5" />
                            {admins.length === 0 ? 'None' : admins.length}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-500">{format(new Date(t.created_at), 'MMM d, yyyy')}</td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={(e) => openEditTenant(e, t)}
                            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-slate-600 hover:bg-slate-200"
                          >
                            <Pencil className="w-3 h-3" />Edit
                          </button>
                        </td>
                      </tr>

                      {/* Expanded admin contacts panel */}
                      {isExpanded && (
                        <tr>
                          <td colSpan={7} className="bg-slate-50 border-t border-slate-200 px-0 py-0">
                            <div className="px-12 py-4">
                              {/* System service user status */}
                              {(() => {
                                const systemUserEmail = `system_ingestion_${t.id}@system.internal`;
                                const hasSystemUser = allUsers.some((u) => u.email === systemUserEmail);
                                const isProvisioning = provisioningTenantId === t.id && provisionSystemUserMutation.isPending;
                                return (
                                  <div className="flex items-center justify-between rounded-lg border bg-white px-4 py-2.5 mb-4">
                                    <div className="flex items-center gap-2 text-sm">
                                      <Bot className="w-4 h-4 text-slate-400" />
                                      <span className="font-medium text-slate-700">Ingestion System User</span>
                                      {hasSystemUser ? (
                                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                                          <CheckCircle className="w-3 h-3" />Ready
                                        </span>
                                      ) : (
                                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                                          <XCircle className="w-3 h-3" />Not provisioned
                                        </span>
                                      )}
                                    </div>
                                    {!hasSystemUser && (
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setProvisioningTenantId(t.id);
                                          provisionSystemUserMutation.mutate(t.id);
                                        }}
                                        disabled={isProvisioning}
                                        className="flex items-center gap-1 rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                                      >
                                        <Bot className="w-3.5 h-3.5" />
                                        {isProvisioning ? 'Provisioning…' : 'Provision Now'}
                                      </button>
                                    )}
                                  </div>
                                );
                              })()}

                              <div className="flex items-center justify-between mb-3">
                                <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                                  <Building2 className="w-4 h-4 text-slate-400" />
                                  {t.name} — Admin Contacts
                                </div>
                                <button
                                  onClick={(e) => openAddAdmin(e, t.id)}
                                  className="flex items-center gap-1 rounded-lg border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/5"
                                >
                                  <PlusCircle className="w-3.5 h-3.5" />Add Admin
                                </button>
                              </div>

                              {admins.length === 0 ? (
                                <p className="text-sm text-slate-400 italic py-2">No admin contacts yet.</p>
                              ) : (
                                <div className="rounded-lg border bg-white overflow-hidden">
                                  <table className="w-full text-sm">
                                    <thead className="bg-slate-50 border-b text-left">
                                      <tr>
                                        <th className="px-4 py-2 font-medium text-slate-600">Name</th>
                                        <th className="px-4 py-2 font-medium text-slate-600">Email</th>
                                        <th className="px-4 py-2 font-medium text-slate-600">Status</th>
                                        <th className="px-4 py-2 font-medium text-slate-600">Since</th>
                                        <th className="px-4 py-2"></th>
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-100">
                                      {admins.map((admin) => (
                                        <tr key={admin.id} className={`hover:bg-slate-50 ${highlightedAdminUserId === admin.id ? 'bg-amber-50' : ''}`}>
                                          <td className="px-4 py-2.5 font-medium text-slate-900">{admin.full_name}</td>
                                          <td className="px-4 py-2.5 text-slate-500 text-xs">{admin.email}</td>
                                          <td className="px-4 py-2.5">
                                            <span
                                              className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${
                                                admin.is_active
                                                  ? 'bg-green-100 text-green-800'
                                                  : 'bg-gray-100 text-gray-600'
                                              }`}
                                            >
                                              {admin.is_active ? 'Active' : 'Inactive'}
                                            </span>
                                          </td>
                                          <td className="px-4 py-2.5 text-slate-400 text-xs">
                                            {format(new Date(admin.created_at), 'MMM d, yyyy')}
                                          </td>
                                          <td className="px-4 py-2.5 text-right">
                                            <AdminActionMenu
                                              isOpen={adminActionMenuId === admin.id}
                                              onToggle={() => setAdminActionMenuId(adminActionMenuId === admin.id ? null : admin.id)}
                                              onClose={() => setAdminActionMenuId(null)}
                                              canResend={!admin.email_verified && !resendVerification.isPending}
                                              resendTooltip={admin.email_verified ? 'User is already verified' : 'Send a fresh verification email'}
                                              adminLabel={admin.full_name}
                                              onEdit={() => openEditAdmin(admin)}
                                              onResend={() => handleResendAdminVerification(admin)}
                                              onResetPassword={() => setAdminResetPassword({ userId: admin.id, value: '', error: '' })}
                                              onDelete={() => setConfirmDeleteUserId(admin.id)}
                                            />
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              )}

                              {/* ── Service Tokens ──────────────────────────── */}
                              <div className="flex items-center justify-between mb-3 mt-5">
                                <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                                  <KeyRound className="w-4 h-4 text-slate-400" />
                                  Service Tokens
                                </div>
                                <button
                                  onClick={(e) => openIssueToken(e, t.id)}
                                  className="flex items-center gap-1 rounded-lg border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/5"
                                >
                                  <PlusCircle className="w-3.5 h-3.5" />Issue Token
                                </button>
                              </div>

                              {tokensLoading ? (
                                <div className="flex items-center gap-2 py-3 text-sm text-slate-400">
                                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600" />
                                  Loading tokens…
                                </div>
                              ) : tokensError ? (
                                <div className="flex items-center gap-2 py-2 text-sm text-red-500">
                                  Failed to load tokens.
                                  <button onClick={() => retryTokens()} className="underline text-xs">Retry</button>
                                </div>
                              ) : serviceTokens.length === 0 ? (
                                <p className="text-sm text-slate-400 italic py-2">No tokens yet.</p>
                              ) : (
                                <div className="space-y-2">
                                  {serviceTokens.map((tok) => (
                                    <div key={tok.id} className="rounded-lg border bg-white px-4 py-3 flex items-start justify-between gap-4">
                                      <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                          <span className="font-medium text-slate-900 text-sm">{tok.name}</span>
                                          <span className="text-xs text-slate-400">issuer: {tok.issuer}</span>
                                        </div>
                                        <div className="flex items-center gap-2 mt-1 flex-wrap">
                                          {tok.is_active ? (
                                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                                              <CheckCircle className="w-3 h-3" />Active
                                            </span>
                                          ) : (
                                            <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
                                              <XCircle className="w-3 h-3" />Revoked
                                            </span>
                                          )}
                                          <span className="text-xs text-slate-400">
                                            Last used: {tok.last_used_at ? format(new Date(tok.last_used_at), 'dd MMM yyyy HH:mm') : 'Never'}
                                          </span>
                                        </div>
                                      </div>
                                      {tok.is_active && (
                                        <button
                                          onClick={(e) => { e.stopPropagation(); setConfirmRevokeToken({ tenantId: t.id, token: tok }); }}
                                          className="flex-shrink-0 rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
                                        >
                                          Revoke
                                        </button>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* ── Tenant Create/Edit Modal ──────────────────────────────────────── */}
      {isTenantModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <h2 className="text-base font-semibold text-slate-900">
                {editingTenant ? `Edit — ${editingTenant.name}` : 'New Tenant'}
              </h2>
              <button onClick={closeTenantModal} className="rounded p-1 hover:bg-slate-100">
                <X className="w-4 h-4 text-slate-500" />
              </button>
            </div>
            <form onSubmit={handleTenantSubmit} className="p-5 space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Name</label>
                <input
                  className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                  value={tenantForm.name}
                  onChange={(e) => setTenantForm((f) => ({ ...f, name: e.target.value, slug: editingTenant ? f.slug : slugify(e.target.value) }))}
                  placeholder="Acme Corp"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Slug</label>
                <input
                  className="w-full rounded-lg border px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/40"
                  value={tenantForm.slug}
                  onChange={(e) => setTenantForm((f) => ({ ...f, slug: e.target.value.toLowerCase() }))}
                  placeholder="acme-corp"
                  required
                />
                <p className="mt-1 text-xs text-slate-400">Lowercase letters, numbers, and hyphens only</p>
              </div>
              {editingTenant && (
                <div className="space-y-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">Status</label>
                    <select
                      className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                      value={tenantForm.status}
                      onChange={(e) => setTenantForm((f) => ({ ...f, status: e.target.value as TenantStatus }))}
                    >
                      <option value="active">Active</option>
                      <option value="inactive">Inactive</option>
                      <option value="suspended">Suspended</option>
                    </select>
                  </div>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={tenantForm.ingestion_enabled}
                      onChange={(e) => setTenantForm((f) => ({ ...f, ingestion_enabled: e.target.checked }))}
                    />
                    Enable ingestion for this tenant
                  </label>
                  {tenantForm.ingestion_enabled && (
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-1">Max mailboxes</label>
                      <input
                        type="number"
                        min="0"
                        placeholder="Leave blank for unlimited"
                        className="w-full rounded-lg border px-3 py-2 text-sm"
                        value={tenantForm.max_mailboxes}
                        onChange={(e) => setTenantForm((f) => ({ ...f, max_mailboxes: e.target.value }))}
                      />
                      <p className="text-xs text-slate-500 mt-1">Cap on mailboxes this tenant can connect. Blank = unlimited.</p>
                    </div>
                  )}
                </div>
              )}
              {tenantFormError && <p className="text-xs text-red-600">{tenantFormError}</p>}
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={closeTenantModal} className="rounded-lg border px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Cancel</button>
                <button type="submit" disabled={isTenantPending} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                  {isTenantPending ? 'Saving…' : editingTenant ? 'Save Changes' : 'Create Tenant'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Add Admin Contact Modal ───────────────────────────────────────── */}
      {addAdminForTenantId != null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <h2 className="text-base font-semibold text-slate-900">Add Admin Contact</h2>
              <button onClick={closeAdminModal} className="rounded p-1 hover:bg-slate-100">
                <X className="w-4 h-4 text-slate-500" />
              </button>
            </div>
            <form onSubmit={handleAdminSubmit} className="p-5 space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Full Name</label>
                <input
                  className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                  value={adminForm.full_name}
                  onChange={(e) => setAdminForm((f) => ({ ...f, full_name: e.target.value }))}
                  placeholder="Jane Smith"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Email</label>
                <input
                  type="email"
                  className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                  value={adminForm.email}
                  onChange={(e) => setAdminForm((f) => ({ ...f, email: e.target.value }))}
                  placeholder="jane@acme.com"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Username</label>
                <input
                  className="w-full rounded-lg border px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/40"
                  value={adminForm.username}
                  onChange={(e) => setAdminForm((f) => ({ ...f, username: e.target.value.toLowerCase() }))}
                  placeholder="jane.smith"
                  minLength={3}
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Initial Password</label>
                <input
                  className="w-full rounded-lg border px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/40"
                  value={adminForm.password}
                  onChange={(e) => setAdminForm((f) => ({ ...f, password: e.target.value }))}
                  required
                />
              </div>
              {adminFormError && <p className="text-xs text-red-600">{adminFormError}</p>}
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={closeAdminModal} className="rounded-lg border px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Cancel</button>
                <button type="submit" disabled={createUserMutation.isPending} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                  {createUserMutation.isPending ? 'Adding…' : 'Add Contact'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Delete Confirmation ───────────────────────────────────────────── */}
      {confirmDeleteUserId != null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm rounded-xl bg-white shadow-2xl p-6">
            <h2 className="text-base font-semibold text-slate-900 mb-2">Remove Admin Contact?</h2>
            <p className="text-sm text-slate-500 mb-6">
              This will permanently delete <strong>{allUsers.find((u) => u.id === confirmDeleteUserId)?.full_name}</strong>. This cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setConfirmDeleteUserId(null)} className="rounded-lg border px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Cancel</button>
              <button
                onClick={() => { deleteUserMutation.mutate(confirmDeleteUserId); setConfirmDeleteUserId(null); }}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
              >
                Remove
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Edit Admin Modal ──────────────────────────────────────────────── */}
      {editingAdmin && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <h2 className="text-base font-semibold text-slate-900">Edit Admin · {editingAdmin.full_name}</h2>
              <button onClick={closeEditAdmin} className="rounded p-1 hover:bg-slate-100">
                <X className="w-4 h-4 text-slate-500" />
              </button>
            </div>
            <form onSubmit={handleEditAdminSubmit} className="p-5 space-y-4">
              <div>
                <label className="block text-xs font-medium uppercase tracking-wide text-slate-500 mb-1">Full Name</label>
                <input
                  value={editAdminForm.full_name}
                  onChange={(e) => setEditAdminForm((f) => ({ ...f, full_name: e.target.value }))}
                  className="w-full rounded-lg border px-3 py-2 text-sm"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-medium uppercase tracking-wide text-slate-500 mb-1">Email</label>
                <input
                  type="email"
                  value={editAdminForm.email}
                  onChange={(e) => setEditAdminForm((f) => ({ ...f, email: e.target.value }))}
                  className="w-full rounded-lg border px-3 py-2 text-sm"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-medium uppercase tracking-wide text-slate-500 mb-1">Username</label>
                <input
                  value={editAdminForm.username}
                  onChange={(e) => setEditAdminForm((f) => ({ ...f, username: e.target.value }))}
                  className="w-full rounded-lg border px-3 py-2 text-sm"
                  minLength={3}
                  required
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={editAdminForm.is_active}
                  onChange={(e) => setEditAdminForm((f) => ({ ...f, is_active: e.target.checked }))}
                />
                Active
              </label>
              {editAdminError && <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{editAdminError}</p>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={closeEditAdmin} className="rounded-lg border px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Cancel</button>
                <button
                  type="submit"
                  disabled={updateUserMutation.isPending}
                  className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 disabled:opacity-60"
                >
                  {updateUserMutation.isPending ? 'Saving…' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Reset Admin Password Modal ───────────────────────────────────── */}
      {adminResetPassword && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm rounded-xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <h2 className="text-base font-semibold text-slate-900">Reset Password</h2>
              <button onClick={() => setAdminResetPassword(null)} className="rounded p-1 hover:bg-slate-100">
                <X className="w-4 h-4 text-slate-500" />
              </button>
            </div>
            <form onSubmit={handleResetAdminPasswordSubmit} className="p-5 space-y-4">
              <p className="text-sm text-slate-500">
                Set a new password for <strong>{allUsers.find((u) => u.id === adminResetPassword.userId)?.full_name}</strong>. They will need to use this password at next login.
              </p>
              <div>
                <label className="block text-xs font-medium uppercase tracking-wide text-slate-500 mb-1">New Password</label>
                <input
                  type="password"
                  autoFocus
                  value={adminResetPassword.value}
                  onChange={(e) => setAdminResetPassword({ ...adminResetPassword, value: e.target.value, error: '' })}
                  className="w-full rounded-lg border px-3 py-2 text-sm"
                  minLength={8}
                  required
                />
              </div>
              {adminResetPassword.error && <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{adminResetPassword.error}</p>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={() => setAdminResetPassword(null)} className="rounded-lg border px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Cancel</button>
                <button
                  type="submit"
                  disabled={resetUserPassword.isPending}
                  className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 disabled:opacity-60"
                >
                  {resetUserPassword.isPending ? 'Saving…' : 'Reset Password'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Issue Service Token Modal ─────────────────────────────────────── */}
      {issueTokenForTenantId != null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <h2 className="text-base font-semibold text-slate-900">
                {issuedToken ? 'Token Issued Successfully' : 'Issue Service Token'}
              </h2>
              <button onClick={closeTokenModal} className="rounded p-1 hover:bg-slate-100">
                <X className="w-4 h-4 text-slate-500" />
              </button>
            </div>

            {issuedToken ? (
              <div className="p-5 space-y-4">
                <div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
                  <span className="text-base leading-none mt-0.5">⚠</span>
                  <span>Copy this token now. It will not be shown again.</span>
                </div>
                <div className="rounded-lg border bg-slate-50 px-4 py-3 font-mono text-sm text-slate-800 break-all select-all">
                  {issuedToken.token}
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(issuedToken.token);
                      setCopiedToken(true);
                      setTimeout(() => setCopiedToken(false), 2000);
                    }}
                    className="rounded-lg border px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    {copiedToken ? 'Copied ✓' : 'Copy Token'}
                  </button>
                  <button
                    onClick={closeTokenModal}
                    className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                  >
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleTokenSubmit} className="p-5 space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">Token name</label>
                  <input
                    className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                    value={tokenForm.name}
                    onChange={(e) => setTokenForm((f) => ({ ...f, name: e.target.value }))}
                    placeholder='e.g. "Ingestion Platform"'
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">Issuer</label>
                  <input
                    className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                    value={tokenForm.issuer}
                    onChange={(e) => setTokenForm((f) => ({ ...f, issuer: e.target.value }))}
                    placeholder='e.g. "ingestion_platform"'
                    required
                  />
                </div>
                {tokenFormError && <p className="text-xs text-red-600">{tokenFormError}</p>}
                <div className="flex justify-end gap-2 pt-2">
                  <button type="button" onClick={closeTokenModal} className="rounded-lg border px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">Cancel</button>
                  <button
                    type="submit"
                    disabled={issueTokenMutation.isPending}
                    className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                  >
                    {issueTokenMutation.isPending ? 'Issuing…' : 'Issue Token'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* ── Revoke Token Confirmation ─────────────────────────────────────── */}
      {confirmRevokeToken != null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm rounded-xl bg-white shadow-2xl p-6">
            <h2 className="text-base font-semibold text-slate-900 mb-2">Revoke this token?</h2>
            <p className="text-sm text-slate-500 mb-6">
              The ingestion platform will immediately lose access until a new token is configured.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirmRevokeToken(null)}
                className="rounded-lg border px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={() => revokeTokenMutation.mutate({ tenantId: confirmRevokeToken.tenantId, tokenId: confirmRevokeToken.token.id })}
                disabled={revokeTokenMutation.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {revokeTokenMutation.isPending ? 'Revoking…' : 'Revoke'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
