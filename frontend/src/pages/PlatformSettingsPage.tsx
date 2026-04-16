import React, { useState } from 'react';
import { Eye, EyeOff, Mail, PlusCircle, Settings, Shield } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { platformSettingsAPI, SmtpConfigUpdate } from '@/api/endpoints';
import { useUsers, useCreateUser, useDeleteUser } from '@/hooks';
import { UserRole } from '@/types';

const apiError = (e: unknown) =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Something went wrong';

type AdminFormState = { full_name: string; email: string; username: string };
const emptyAdminForm = (): AdminFormState => ({ full_name: '', email: '', username: '' });

// ─── SMTP Form ─────────────────────────────────────────────────────────────

const SmtpSection: React.FC = () => {
  const qc = useQueryClient();
  const [showPassword, setShowPassword] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [smtpForm, setSmtpForm] = useState<SmtpConfigUpdate>({
    smtp_host: '',
    smtp_port: 587,
    smtp_username: '',
    smtp_password: null,
    smtp_from_address: '',
    smtp_from_name: '',
    smtp_use_tls: true,
  });
  const [formError, setFormError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  const { data: config, isLoading } = useQuery({
    queryKey: ['platform-smtp'],
    queryFn: () => platformSettingsAPI.getSmtp().then((r) => r.data),
  });

  const saveMutation = useMutation({
    mutationFn: (data: SmtpConfigUpdate) => platformSettingsAPI.updateSmtp(data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platform-smtp'] });
      setEditMode(false);
      setSuccessMsg('SMTP configuration saved.');
      setTimeout(() => setSuccessMsg(''), 4000);
    },
    onError: (e) => setFormError(apiError(e)),
  });

  const clearMutation = useMutation({
    mutationFn: () => platformSettingsAPI.clearSmtp().then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platform-smtp'] });
      setSuccessMsg('SMTP configuration cleared — environment variables are now active.');
      setTimeout(() => setSuccessMsg(''), 4000);
    },
    onError: (e) => setFormError(apiError(e)),
  });

  const openEdit = () => {
    setFormError('');
    setSmtpForm({
      smtp_host: config?.smtp_host ?? '',
      smtp_port: config?.smtp_port ?? 587,
      smtp_username: config?.smtp_username ?? '',
      smtp_password: null, // don't pre-fill password; null = keep existing
      smtp_from_address: config?.smtp_from_address ?? '',
      smtp_from_name: config?.smtp_from_name ?? '',
      smtp_use_tls: config?.smtp_use_tls ?? true,
    });
    setEditMode(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    saveMutation.mutate(smtpForm);
  };

  const field = (key: keyof SmtpConfigUpdate) => (
    (e: React.ChangeEvent<HTMLInputElement>) =>
      setSmtpForm((prev) => ({ ...prev, [key]: e.target.value }))
  );

  if (isLoading) {
    return <div className="rounded-xl border border-border bg-muted shadow-sm p-5 animate-pulse h-32" />;
  }

  return (
    <div className="rounded-xl border border-border bg-card shadow-sm p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Mail className="w-5 h-5 text-primary" />
          <div>
            <h2 className="text-lg font-semibold text-foreground">SMTP Configuration</h2>
            <p className="text-xs text-muted-foreground">
              Outbound email settings for verification and notification emails.{' '}
              {config?.source === 'environment' && (
                <span className="text-amber-600 font-medium">Currently using environment variables.</span>
              )}
              {config?.source === 'database' && (
                <span className="text-emerald-600 font-medium">Using database configuration.</span>
              )}
            </p>
          </div>
        </div>
        {!editMode && (
          <div className="flex gap-2">
            {config?.source === 'database' && (
              <button
                onClick={() => clearMutation.mutate()}
                disabled={clearMutation.isPending}
                className="text-xs text-red-600 hover:underline disabled:opacity-50"
              >
                {clearMutation.isPending ? 'Clearing…' : 'Reset to env vars'}
              </button>
            )}
            <button
              onClick={openEdit}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            >
              {config?.smtp_host ? 'Edit' : 'Configure'}
            </button>
          </div>
        )}
      </div>

      {successMsg && (
        <div className="mb-3 rounded-lg bg-emerald-50 border border-emerald-200 px-3 py-2 text-sm text-emerald-700">
          {successMsg}
        </div>
      )}

      {!editMode && config && (
        config.smtp_host ? (
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <div><dt className="text-muted-foreground text-xs font-medium uppercase tracking-wide">Host</dt><dd className="font-mono text-foreground">{config.smtp_host}:{config.smtp_port}</dd></div>
            <div><dt className="text-muted-foreground text-xs font-medium uppercase tracking-wide">Username</dt><dd className="font-mono text-foreground">{config.smtp_username || '—'}</dd></div>
            <div><dt className="text-muted-foreground text-xs font-medium uppercase tracking-wide">Password</dt><dd className="text-foreground">{config.smtp_password_set ? '••••••••' : '—'}</dd></div>
            <div><dt className="text-muted-foreground text-xs font-medium uppercase tracking-wide">TLS</dt><dd className="text-foreground">{config.smtp_use_tls ? 'Enabled' : 'Disabled'}</dd></div>
            <div><dt className="text-muted-foreground text-xs font-medium uppercase tracking-wide">From Address</dt><dd className="text-foreground">{config.smtp_from_address || '—'}</dd></div>
            <div><dt className="text-muted-foreground text-xs font-medium uppercase tracking-wide">From Name</dt><dd className="text-foreground">{config.smtp_from_name || '—'}</dd></div>
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">No SMTP server configured. Verification emails will be logged to the console.</p>
        )
      )}

      {editMode && (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="flex gap-2">
              <div className="flex-1">
                <label className="block text-xs font-medium text-foreground mb-1">SMTP Host</label>
                <input
                  placeholder="smtp.sendgrid.net"
                  className="field-input w-full"
                  value={smtpForm.smtp_host}
                  onChange={field('smtp_host')}
                />
              </div>
              <div className="w-24">
                <label className="block text-xs font-medium text-foreground mb-1">Port</label>
                <input
                  type="number"
                  className="field-input w-full"
                  value={smtpForm.smtp_port}
                  onChange={(e) => setSmtpForm((p) => ({ ...p, smtp_port: Number(e.target.value) }))}
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-foreground mb-1">Username</label>
              <input
                placeholder="apikey"
                className="field-input w-full"
                value={smtpForm.smtp_username}
                onChange={field('smtp_username')}
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-foreground mb-1">
                Password{' '}
                {config?.smtp_password_set && (
                  <span className="text-muted-foreground font-normal">(leave blank to keep existing)</span>
                )}
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  placeholder={config?.smtp_password_set ? '••••••••' : 'Enter password'}
                  className="field-input w-full pr-9"
                  value={smtpForm.smtp_password ?? ''}
                  onChange={(e) => setSmtpForm((p) => ({ ...p, smtp_password: e.target.value || null }))}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-foreground mb-1">From Address</label>
              <input
                type="email"
                placeholder="no-reply@yourdomain.com"
                className="field-input w-full"
                value={smtpForm.smtp_from_address}
                onChange={field('smtp_from_address')}
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-foreground mb-1">From Name</label>
              <input
                placeholder="TimesheetIQ"
                className="field-input w-full"
                value={smtpForm.smtp_from_name}
                onChange={field('smtp_from_name')}
              />
            </div>

            <div className="flex items-center gap-2 pt-5">
              <input
                id="smtp-tls"
                type="checkbox"
                className="h-4 w-4 rounded border-border text-primary"
                checked={smtpForm.smtp_use_tls}
                onChange={(e) => setSmtpForm((p) => ({ ...p, smtp_use_tls: e.target.checked }))}
              />
              <label htmlFor="smtp-tls" className="text-sm text-foreground">Use STARTTLS</label>
            </div>
          </div>

          {formError && <p className="text-xs text-red-600">{formError}</p>}

          <div className="flex gap-2">
            <button
              type="submit"
              disabled={saveMutation.isPending}
              className="action-button text-sm"
            >
              {saveMutation.isPending ? 'Saving…' : 'Save SMTP Config'}
            </button>
            <button
              type="button"
              onClick={() => setEditMode(false)}
              className="action-button-secondary text-sm"
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
};

// ─── Platform Admins Section ───────────────────────────────────────────────

const PlatformAdminsSection: React.FC = () => {
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState<AdminFormState>(emptyAdminForm());
  const [formError, setFormError] = useState('');
  const [createdEmail, setCreatedEmail] = useState<string | null>(null);

  const { data: allUsers = [] } = useUsers();
  const platformAdmins = allUsers.filter((u) => u.role === 'PLATFORM_ADMIN');

  const createUserMutation = useCreateUser();
  const deleteUserMutation = useDeleteUser();
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const confirmDeleteUser = platformAdmins.find((u) => u.id === confirmDeleteId);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    if (!form.full_name.trim() || !form.email.trim() || !form.username.trim()) {
      setFormError('All fields are required');
      return;
    }
    createUserMutation.mutate(
      {
        full_name: form.full_name,
        email: form.email,
        username: form.username,
        role: 'PLATFORM_ADMIN' as UserRole,
      },
      {
        onSuccess: (result) => {
          void result; // temporary_password intentionally not surfaced — user sets one via verification link.
          setShowAdd(false);
          setForm(emptyAdminForm());
          setFormError('');
          setCreatedEmail(form.email);
        },
        onError: (err) => setFormError(apiError(err)),
      },
    );
  };

  return (
    <div className="rounded-xl border border-border bg-card shadow-sm p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-primary" />
          <div>
            <h2 className="text-lg font-semibold text-foreground">Platform Admins</h2>
            <p className="text-xs text-muted-foreground">Users with cross-tenant superuser access</p>
          </div>
        </div>
        <button
          onClick={() => { setForm(emptyAdminForm()); setFormError(''); setShowAdd(true); }}
          className="flex items-center gap-1.5 rounded-lg bg-muted px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted/80"
        >
          <PlusCircle className="w-3.5 h-3.5" /> Add Platform Admin
        </button>
      </div>

      {platformAdmins.length === 0 ? (
        <p className="text-sm text-muted-foreground">No platform admins found.</p>
      ) : (
        <div className="space-y-2">
          {platformAdmins.map((pa) => (
            <div key={pa.id} className="flex items-center justify-between rounded-lg border border-border px-4 py-2.5">
              <div>
                <span className="font-medium text-sm text-foreground">{pa.full_name}</span>
                <span className="ml-2 text-xs text-muted-foreground">{pa.email}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${pa.is_active ? 'bg-emerald-100 text-emerald-800' : 'bg-muted text-foreground'}`}>
                  {pa.is_active ? 'Active' : 'Inactive'}
                </span>
                <button
                  onClick={() => setConfirmDeleteId(pa.id)}
                  className="text-xs text-red-500 hover:text-red-700"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showAdd && (
        <form onSubmit={handleSubmit} className="mt-4 rounded-lg border border-border bg-muted/40 p-4 space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <input
              placeholder="Full name"
              className="field-input"
              required
              value={form.full_name}
              onChange={(e) => setForm((p) => ({ ...p, full_name: e.target.value }))}
            />
            <input
              placeholder="Email"
              type="email"
              className="field-input"
              required
              value={form.email}
              onChange={(e) => setForm((p) => ({ ...p, email: e.target.value }))}
            />
            <input
              placeholder="Username"
              className="field-input"
              required
              value={form.username}
              onChange={(e) => setForm((p) => ({ ...p, username: e.target.value }))}
            />
          </div>
          <p className="text-xs text-muted-foreground">A temporary password will be generated automatically.</p>
          {formError && <p className="text-xs text-red-600">{formError}</p>}
          <div className="flex gap-2">
            <button type="submit" disabled={createUserMutation.isPending} className="action-button text-sm">
              {createUserMutation.isPending ? 'Creating…' : 'Create Platform Admin'}
            </button>
            <button type="button" onClick={() => setShowAdd(false)} className="action-button-secondary text-sm">
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Verification-sent dialog */}
      {createdEmail && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-card rounded-xl shadow-2xl p-6 border border-border w-full max-w-md">
            <h3 className="text-lg font-semibold text-foreground mb-1">Platform Admin Created</h3>
            <p className="text-sm text-muted-foreground mb-4">
              Verification email sent to <span className="font-medium text-foreground">{createdEmail}</span>.
            </p>
            <div className="flex justify-end">
              <button
                onClick={() => setCreatedEmail(null)}
                className="action-button text-sm"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      {confirmDeleteId != null && confirmDeleteUser && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-card rounded-xl shadow-2xl p-6 border border-border w-full max-w-sm">
            <h3 className="text-lg font-semibold text-foreground mb-2">Remove Platform Admin</h3>
            <p className="text-sm text-foreground mb-4">
              Permanently delete <strong>{confirmDeleteUser.full_name}</strong> ({confirmDeleteUser.email})?
              This cannot be undone.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  deleteUserMutation.mutate(confirmDeleteId, {
                    onSettled: () => setConfirmDeleteId(null),
                  });
                }}
                disabled={deleteUserMutation.isPending}
                className="flex-1 rounded-lg bg-red-600 text-white px-4 py-2 text-sm font-medium hover:bg-red-700 disabled:opacity-50"
              >
                {deleteUserMutation.isPending ? 'Deleting…' : 'Delete'}
              </button>
              <button
                onClick={() => setConfirmDeleteId(null)}
                className="action-button-secondary text-sm"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ─── Page ──────────────────────────────────────────────────────────────────

export const PlatformSettingsPage: React.FC = () => {
  return (
    <div className="p-1">
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="flex items-center gap-3 mb-2">
          <Settings className="w-6 h-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold text-foreground">Platform Settings</h1>
            <p className="text-sm text-muted-foreground">Manage platform-level configuration and administrators</p>
          </div>
        </div>

        <PlatformAdminsSection />
        <SmtpSection />
      </div>
    </div>
  );
};
