import React, { useMemo, useState } from 'react';
import { Download, Loader2, X } from 'lucide-react';

import {
  useClients,
  useExportClients,
  useExportTimesheets,
  useExportUsers,
  useProjects,
  useUsers,
} from '@/hooks';
import { cn } from '@/lib/utils';
import type { Client, Project, User } from '@/types';

type ExportType = 'users' | 'clients' | 'timesheets';
type Fmt = 'csv' | 'xlsx';
type UserType = 'all' | 'internal' | 'external';
type StatusFilter = 'all' | 'active' | 'inactive';

interface Props {
  onClose: () => void;
}

function firstOfMonth(d: Date): string {
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
}
function lastOfMonth(d: Date): string {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0).toISOString().slice(0, 10);
}
function firstOfQuarter(d: Date): string {
  const qm = Math.floor(d.getMonth() / 3) * 3;
  return new Date(d.getFullYear(), qm, 1).toISOString().slice(0, 10);
}
function lastOfQuarter(d: Date): string {
  const qm = Math.floor(d.getMonth() / 3) * 3;
  return new Date(d.getFullYear(), qm + 3, 0).toISOString().slice(0, 10);
}
function firstOfYear(d: Date): string {
  return new Date(d.getFullYear(), 0, 1).toISOString().slice(0, 10);
}
function lastOfYear(d: Date): string {
  return new Date(d.getFullYear(), 11, 31).toISOString().slice(0, 10);
}

export const ExportModal: React.FC<Props> = ({ onClose }) => {
  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const [exportType, setExportType] = useState<ExportType>('users');
  const [fmt, setFmt] = useState<Fmt>('csv');

  // Users export filters
  const [usersUserType, setUsersUserType] = useState<UserType>('all');
  const [usersStatus, setUsersStatus] = useState<StatusFilter>('all');
  const [usersClientId, setUsersClientId] = useState<string>('');
  const [usersRole, setUsersRole] = useState<string>('');

  // Timesheets export filters
  const [tsUserType, setTsUserType] = useState<UserType>('all');
  const [tsUserId, setTsUserId] = useState<string>('');
  const [tsClientId, setTsClientId] = useState<string>('');
  const [tsProjectId, setTsProjectId] = useState<string>('');

  const today = useMemo(() => new Date(), []);
  type Preset = 'month' | 'quarter' | 'year' | 'custom';
  const [preset, setPreset] = useState<Preset>('month');
  const [periodStart, setPeriodStart] = useState<string>(firstOfMonth(today));
  const [periodEnd, setPeriodEnd] = useState<string>(lastOfMonth(today));

  const applyPreset = (p: Preset) => {
    setPreset(p);
    if (p === 'month') {
      setPeriodStart(firstOfMonth(today));
      setPeriodEnd(lastOfMonth(today));
    } else if (p === 'quarter') {
      setPeriodStart(firstOfQuarter(today));
      setPeriodEnd(lastOfQuarter(today));
    } else if (p === 'year') {
      setPeriodStart(firstOfYear(today));
      setPeriodEnd(lastOfYear(today));
    }
  };

  const { data: users } = useUsers();
  const { data: clients } = useClients();
  const { data: projects } = useProjects();

  const exportUsers = useExportUsers();
  const exportClients = useExportClients();
  const exportTimesheets = useExportTimesheets();

  const isPending =
    exportUsers.isPending || exportClients.isPending || exportTimesheets.isPending;

  const [error, setError] = useState<string | null>(null);

  const handleExport = async () => {
    setError(null);
    try {
      if (exportType === 'users') {
        await exportUsers.mutateAsync({
          fmt,
          user_type: usersUserType,
          status_filter: usersStatus,
          ...(usersClientId ? { client_id: Number(usersClientId) } : {}),
          ...(usersRole ? { role: usersRole } : {}),
        });
      } else if (exportType === 'clients') {
        await exportClients.mutateAsync({ fmt });
      } else {
        if (!periodStart || !periodEnd) {
          setError('Period start and end are required.');
          return;
        }
        await exportTimesheets.mutateAsync({
          fmt,
          period_start: periodStart,
          period_end: periodEnd,
          user_type: tsUserType,
          ...(tsUserId ? { user_id: Number(tsUserId) } : {}),
          ...(tsClientId ? { client_id: Number(tsClientId) } : {}),
          ...(tsProjectId ? { project_id: Number(tsProjectId) } : {}),
        });
      }
      onClose();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || 'Export failed. Please try again.');
    }
  };

  const filteredProjects = useMemo<Project[]>(() => {
    if (!projects) return [];
    if (!tsClientId) return projects;
    return projects.filter((p: Project) => String(p.client_id) === tsClientId);
  }, [projects, tsClientId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="flex w-full max-w-2xl flex-col rounded-xl border border-border bg-card shadow-xl max-h-[90vh]">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold">Export Data</h2>
            <p className="text-xs text-muted-foreground mt-0.5">Download as CSV or Excel</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 hover:bg-muted">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          <div>
            <label className="text-sm font-medium mb-2 block">What to export</label>
            <div className="grid grid-cols-3 gap-2">
              {(['users', 'clients', 'timesheets'] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setExportType(t)}
                  className={cn(
                    'rounded-lg border px-3 py-2 text-sm font-medium transition',
                    exportType === t
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border hover:bg-muted',
                  )}
                >
                  {t === 'users' ? 'Users' : t === 'clients' ? 'Clients' : 'Approved Timesheets'}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block">File format</label>
            <div className="flex gap-2">
              {(['csv', 'xlsx'] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setFmt(f)}
                  className={cn(
                    'rounded-lg border px-4 py-1.5 text-sm font-medium transition',
                    fmt === f
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border hover:bg-muted',
                  )}
                >
                  {f.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {exportType === 'users' && (
            <div className="space-y-3 border-t pt-4">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">User Filters</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium mb-1 block">User type</label>
                  <select
                    value={usersUserType}
                    onChange={(e) => setUsersUserType(e.target.value as UserType)}
                    className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                  >
                    <option value="all">All</option>
                    <option value="internal">Internal only</option>
                    <option value="external">External only</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block">Status</label>
                  <select
                    value={usersStatus}
                    onChange={(e) => setUsersStatus(e.target.value as StatusFilter)}
                    className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                  >
                    <option value="all">All</option>
                    <option value="active">Active only</option>
                    <option value="inactive">Inactive only</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block">Role</label>
                  <select
                    value={usersRole}
                    onChange={(e) => setUsersRole(e.target.value)}
                    className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                  >
                    <option value="">All roles</option>
                    <option value="EMPLOYEE">Employee</option>
                    <option value="MANAGER">Manager</option>
                    <option value="VIEWER">Viewer</option>
                    <option value="ADMIN">Admin</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block">Default client</label>
                  <select
                    value={usersClientId}
                    onChange={(e) => setUsersClientId(e.target.value)}
                    className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                  >
                    <option value="">Any</option>
                    {clients?.map((c: Client) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>
          )}

          {exportType === 'timesheets' && (
            <div className="space-y-3 border-t pt-4">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Timesheet Filters</p>

              <div>
                <label className="text-xs font-medium mb-1 block">Period</label>
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {(['month', 'quarter', 'year', 'custom'] as const).map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => applyPreset(p)}
                      className={cn(
                        'rounded-lg border px-2.5 py-1 text-xs font-medium transition',
                        preset === p
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'border-border hover:bg-muted',
                      )}
                    >
                      {p === 'month' ? 'This month' : p === 'quarter' ? 'This quarter' : p === 'year' ? 'This year' : 'Custom'}
                    </button>
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <input
                    type="date"
                    value={periodStart}
                    onChange={(e) => { setPreset('custom'); setPeriodStart(e.target.value); }}
                    className="rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                  />
                  <input
                    type="date"
                    value={periodEnd}
                    onChange={(e) => { setPreset('custom'); setPeriodEnd(e.target.value); }}
                    className="rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium mb-1 block">User type</label>
                  <select
                    value={tsUserType}
                    onChange={(e) => setTsUserType(e.target.value as UserType)}
                    className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                  >
                    <option value="all">All</option>
                    <option value="internal">Internal only</option>
                    <option value="external">External only</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block">Specific employee</label>
                  <select
                    value={tsUserId}
                    onChange={(e) => setTsUserId(e.target.value)}
                    className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                  >
                    <option value="">All</option>
                    {users?.map((u: User) => (
                      <option key={u.id} value={u.id}>{u.full_name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block">Client</label>
                  <select
                    value={tsClientId}
                    onChange={(e) => { setTsClientId(e.target.value); setTsProjectId(''); }}
                    className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                  >
                    <option value="">All</option>
                    {clients?.map((c: Client) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block">Project</label>
                  <select
                    value={tsProjectId}
                    onChange={(e) => setTsProjectId(e.target.value)}
                    className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                  >
                    <option value="">All</option>
                    {filteredProjects?.map((p: Project) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>
          )}

          {exportType === 'clients' && (
            <div className="border-t pt-4 text-sm text-muted-foreground">
              All clients will be exported with their email domains, contacts, and project counts.
            </div>
          )}

          {error && (
            <div className="rounded border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-muted-foreground hover:bg-muted transition"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleExport}
            disabled={isPending}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50 hover:bg-primary/90 transition"
          >
            {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            Export {fmt.toUpperCase()}
          </button>
        </div>
      </div>
    </div>
  );
};
