import React from 'react';
import { ExternalLink, Mail, Plus, Plug, RefreshCw, RotateCcw, ShieldCheck, Trash2, X } from 'lucide-react';
import axios from 'axios';

import { apiClient } from '@/api/client';
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Loading } from '@/components';
import { mailboxesAPI } from '@/api/endpoints';
import { useAuth, useClients, useCreateMailbox, useDeleteMailbox, useMailboxes, useResetMailboxCursor, useTestMailbox, useUpdateMailbox, useTenantSettings, useUpdateTenantSettings } from '@/hooks';
import type { Mailbox, MailboxPayload, OAuthProvider } from '@/types';

type FormState = {
  label: string;
  protocol: string;
  auth_type: string;
  host: string;
  port: string;
  use_ssl: boolean;
  username: string;
  password: string;
  oauth_provider: OAuthProvider | '';
  smtp_host: string;
  smtp_port: string;
  smtp_username: string;
  smtp_password: string;
  linked_client_id: string;
  is_active: boolean;
};

const createEmptyForm = (): FormState => ({
  label: '',
  protocol: 'imap',
  auth_type: 'basic',
  host: '',
  port: '993',
  use_ssl: true,
  username: '',
  password: '',
  oauth_provider: '',
  smtp_host: '',
  smtp_port: '',
  smtp_username: '',
  smtp_password: '',
  linked_client_id: '',
  is_active: true,
});

const toPayload = (form: FormState): MailboxPayload => ({
  label: form.label.trim(),
  protocol: form.protocol,
  auth_type: form.auth_type,
  host: form.auth_type === 'basic' ? (form.host.trim() || null) : null,
  port: form.port ? Number(form.port) : null,
  use_ssl: form.use_ssl,
  username: form.username.trim() || null,
  password: form.password.trim() || undefined,
  oauth_provider: form.auth_type === 'oauth2' ? (form.oauth_provider || null) : null,
  smtp_host: form.smtp_host.trim() || null,
  smtp_port: form.smtp_port ? Number(form.smtp_port) : null,
  smtp_username: form.smtp_username.trim() || null,
  smtp_password: form.smtp_password.trim() || undefined,
  linked_client_id: form.linked_client_id ? Number(form.linked_client_id) : null,
  is_active: form.is_active,
});

const getApiErrorMessage = (error: unknown, fallback: string): string => {
  if (axios.isAxiosError(error) && typeof error.response?.data?.detail === 'string') {
    return error.response.data.detail;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
};

export const MailboxesPage: React.FC = () => {
  const { data: mailboxes = [], isLoading, refetch: refetchMailboxes } = useMailboxes();
  const { tenant } = useAuth();
  const maxMailboxes = tenant?.max_mailboxes ?? null;
  const activeMailboxCount = mailboxes.filter((m) => m.is_active).length;
  const atCap = maxMailboxes != null && activeMailboxCount >= maxMailboxes;
  const { data: clients = [] } = useClients();
  const createMailbox = useCreateMailbox();
  const updateMailbox = useUpdateMailbox();
  const deleteMailbox = useDeleteMailbox();
  const testMailbox = useTestMailbox();
  const resetCursor = useResetMailboxCursor();
  const { data: tenantSettings = {} } = useTenantSettings();
  const updateSettings = useUpdateTenantSettings();

  const [fetchEnabled, setFetchEnabled] = React.useState(false);
  const [fetchInterval, setFetchInterval] = React.useState('60');
  const [fetchDays, setFetchDays] = React.useState('mon,tue,wed,thu,fri');
  const [fetchStartTime, setFetchStartTime] = React.useState('08:00');
  const [fetchEndTime, setFetchEndTime] = React.useState('20:00');
  const [fetchSaved, setFetchSaved] = React.useState(false);

  React.useEffect(() => {
    if (!tenantSettings || Object.keys(tenantSettings).length === 0) return;
    // Post-catalog endpoints return typed values (bool/int/string) instead
    // of always-strings. Coerce everything to the types this form expects.
    if (tenantSettings.fetch_emails_enabled != null)
      setFetchEnabled(tenantSettings.fetch_emails_enabled === true || tenantSettings.fetch_emails_enabled === 'true');
    if (tenantSettings.fetch_emails_interval_minutes != null)
      setFetchInterval(String(tenantSettings.fetch_emails_interval_minutes));
    if (tenantSettings.fetch_emails_days != null)
      setFetchDays(String(tenantSettings.fetch_emails_days));
    if (tenantSettings.fetch_emails_start_time != null)
      setFetchStartTime(String(tenantSettings.fetch_emails_start_time));
    if (tenantSettings.fetch_emails_end_time != null)
      setFetchEndTime(String(tenantSettings.fetch_emails_end_time));
  }, [tenantSettings]);

  const [isPanelOpen, setIsPanelOpen] = React.useState(false);
  const [editingMailbox, setEditingMailbox] = React.useState<Mailbox | null>(null);
  const [form, setForm] = React.useState<FormState>(createEmptyForm());
  const [statusMessage, setStatusMessage] = React.useState<string | null>(null);
  const [statusTone, setStatusTone] = React.useState<'success' | 'danger' | 'info'>('info');
  const backendOrigin = React.useMemo(
    () => new URL(apiClient.defaults.baseURL ?? window.location.origin).origin,
    [],
  );

  React.useEffect(() => {
    const handleOAuthMessage = (event: MessageEvent) => {
      if (event.origin !== backendOrigin) {
        return;
      }

      const payload = event.data as {
        type?: string;
        status?: 'success' | 'danger';
        message?: string;
      };

      if (payload?.type !== 'mailbox-oauth') {
        return;
      }

      setStatusTone(payload.status === 'success' ? 'success' : 'danger');
      setStatusMessage(payload.message ?? 'Mailbox OAuth completed.');

      if (payload.status === 'success') {
        void refetchMailboxes();
      }
    };

    window.addEventListener('message', handleOAuthMessage);
    return () => window.removeEventListener('message', handleOAuthMessage);
  }, [backendOrigin, refetchMailboxes]);

  if (isLoading) {
    return <Loading message="Loading mailbox configuration..." />;
  }

  const openCreate = () => {
    setEditingMailbox(null);
    setForm(createEmptyForm());
    setIsPanelOpen(true);
    setStatusMessage(null);
  };

  const openEdit = (mailbox: Mailbox) => {
    setEditingMailbox(mailbox);
    setForm({
      label: mailbox.label,
      protocol: String(mailbox.protocol),
      auth_type: String(mailbox.auth_type) === 'oauth' ? 'oauth2' : String(mailbox.auth_type),
      host: mailbox.host ?? '',
      port: mailbox.port ? String(mailbox.port) : '',
      use_ssl: mailbox.use_ssl,
      username: mailbox.username ?? '',
      password: '',
      oauth_provider: (mailbox.oauth_provider as OAuthProvider | null) ?? '',
      smtp_host: mailbox.smtp_host ?? '',
      smtp_port: mailbox.smtp_port ? String(mailbox.smtp_port) : '',
      smtp_username: mailbox.smtp_username ?? '',
      smtp_password: '',
      linked_client_id: mailbox.linked_client_id ? String(mailbox.linked_client_id) : '',
      is_active: mailbox.is_active,
    });
    setIsPanelOpen(true);
    setStatusMessage(null);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const payload = toPayload(form);

    try {
      if (editingMailbox) {
        await updateMailbox.mutateAsync({ id: editingMailbox.id, data: payload });
        setStatusTone('success');
        setStatusMessage(`Updated ${payload.label}.`);
      } else {
        await createMailbox.mutateAsync(payload);
        setStatusTone('success');
        setStatusMessage(`Created ${payload.label}.`);
      }
      setIsPanelOpen(false);
    } catch (error) {
      setStatusTone('danger');
      setStatusMessage(getApiErrorMessage(error, 'Mailbox save failed.'));
    }
  };

  const handleDelete = async (mailbox: Mailbox) => {
    if (!window.confirm(`Delete mailbox "${mailbox.label}"?`)) return;
    try {
      await deleteMailbox.mutateAsync(mailbox.id);
      setStatusTone('success');
      setStatusMessage(`Deleted ${mailbox.label}.`);
    } catch (error) {
      setStatusTone('danger');
      setStatusMessage(getApiErrorMessage(error, 'Delete failed.'));
    }
  };

  const handleTest = async (mailbox: Mailbox) => {
    try {
      const result = await testMailbox.mutateAsync(mailbox.id);
      setStatusTone(result.success ? 'success' : 'danger');
      setStatusMessage(
        result.success
          ? `${mailbox.label} connected in ${result.latency_ms}ms and found ${result.message_count} messages.`
          : `${mailbox.label} test failed: ${result.error || 'unknown error'}`,
      );
    } catch (error) {
      setStatusTone('danger');
      setStatusMessage(getApiErrorMessage(error, 'Connection test failed.'));
    }
  };

  const handleResetCursor = async (mailbox: Mailbox) => {
    if (!window.confirm(`Re-fetch all emails for "${mailbox.label}"? The next fetch will pull all emails from the last 30 days again.`)) return;
    try {
      await resetCursor.mutateAsync(mailbox.id);
      setStatusTone('success');
      setStatusMessage(`Fetch cursor reset for ${mailbox.label}. Next fetch will pull all emails.`);
    } catch (error) {
      setStatusTone('danger');
      setStatusMessage(getApiErrorMessage(error, 'Failed to reset fetch cursor.'));
    }
  };

  const handleOAuthConnect = async (provider: OAuthProvider) => {
    try {
      const response = await mailboxesAPI.oauthConnect(provider);
      window.open(response.data.auth_url, 'mailbox-oauth', 'popup,width=720,height=820');
    } catch (error) {
      setStatusTone('danger');
      setStatusMessage(getApiErrorMessage(error, `Unable to start ${provider} OAuth.`));
    }
  };

  // Reconnect a dead OAuth mailbox; callback upserts on (tenant, provider, oauth_email).
  const handleOAuthReconnect = async (mailbox: Mailbox) => {
    const provider = mailbox.oauth_provider as OAuthProvider | null;
    if (!provider) {
      setStatusTone('danger');
      setStatusMessage('This mailbox has no OAuth provider to reconnect.');
      return;
    }
    await handleOAuthConnect(provider);
  };

  const isOAuthMailbox = (mailbox: Mailbox): boolean =>
    (mailbox.auth_type === 'oauth' || mailbox.auth_type === 'oauth2') &&
    !!mailbox.oauth_provider;

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Mailboxes</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Configure intake mailboxes for timesheet submissions. Passwords never come back from the API once saved.
          </p>
          {maxMailboxes != null && (
            <p className="mt-2 text-xs text-muted-foreground">
              {activeMailboxCount} of {maxMailboxes} connected.
              {atCap && ' Contact the platform admin to raise the limit.'}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="action-button disabled:opacity-50 disabled:cursor-not-allowed"
          disabled={atCap}
          title={atCap ? 'Mailbox limit reached' : 'Add a new mailbox'}
        >
          <Plus className="mr-2 h-4 w-4" />
          New Mailbox
        </button>
      </div>

      {statusMessage && (
        <div className="surface-card px-5 py-4">
          <Badge tone={statusTone}>
            {statusTone === 'success' ? 'Done' : statusTone === 'info' ? 'Info' : 'Something went wrong'}
          </Badge>
          <p className="mt-3 text-sm text-muted-foreground">{statusMessage}</p>
        </div>
      )}

      {mailboxes.length === 0 ? (
        <EmptyState message="No ingestion mailboxes yet. Add one to start staging submissions." />
      ) : (
        <div className="space-y-2">
          {mailboxes.map((mailbox) => (
              <Card key={mailbox.id} className="group">
                <CardHeader className="pb-3">
                <div>
                  <div className="flex items-center gap-3">
                    <CardTitle>{mailbox.label}</CardTitle>
                    <Badge tone={mailbox.is_active ? 'success' : 'outline'}>
                      {mailbox.is_active ? 'Active' : 'Paused'}
                    </Badge>
                  </div>
                  <CardDescription className="mt-2">
                    {mailbox.auth_type === 'oauth' || mailbox.auth_type === 'oauth2'
                      ? `${mailbox.oauth_provider ?? 'OAuth'} mailbox`
                      : `${mailbox.host ?? 'Host pending'}:${mailbox.port ?? '—'} via ${mailbox.protocol}`}
                  </CardDescription>
                </div>
                <Mail className="h-5 w-5 text-muted-foreground" />
              </CardHeader>
              <CardContent className="space-y-4 pt-0">
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="rounded-md bg-muted px-4 py-3">
                    <p className="text-xs uppercase tracking-[0.22em] text-muted-foreground">Username</p>
                    <p className="mt-2 text-sm text-foreground">{mailbox.username || mailbox.oauth_email || 'Not set'}</p>
                  </div>
                  <div className="rounded-md bg-muted px-4 py-3">
                    <p className="text-xs uppercase tracking-[0.22em] text-muted-foreground">Credentials</p>
                    <p className="mt-2 text-sm text-foreground">{mailbox.has_password ? 'Saved securely' : 'Awaiting secret'}</p>
                  </div>
                </div>

                <div className="flex flex-wrap gap-3 opacity-100 transition md:opacity-0 md:group-hover:opacity-100">
                  <button type="button" onClick={() => openEdit(mailbox)} className="action-button-secondary">
                    <RefreshCw className="mr-2 h-4 w-4" />
                    Edit
                  </button>
                  <button type="button" onClick={() => handleTest(mailbox)} className="action-button-secondary">
                    <ShieldCheck className="mr-2 h-4 w-4" />
                    Test
                  </button>
                  {isOAuthMailbox(mailbox) && (
                    <button
                      type="button"
                      onClick={() => void handleOAuthReconnect(mailbox)}
                      className="action-button-secondary"
                      title="Re-authorize this OAuth mailbox (use when the refresh token has expired or been revoked)"
                    >
                      <Plug className="mr-2 h-4 w-4" />
                      Reconnect
                    </button>
                  )}
                  <button type="button" onClick={() => void handleResetCursor(mailbox)} className="action-button-secondary">
                    <RotateCcw className="mr-2 h-4 w-4" />
                    Re-fetch all
                  </button>
                  <button type="button" onClick={() => handleDelete(mailbox)} className="action-button-secondary">
                    <Trash2 className="mr-2 h-4 w-4" />
                    Delete
                  </button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Card>
        <CardHeader>
          <div>
            <CardTitle>OAuth Connections</CardTitle>
            <CardDescription className="mt-2">
              Use provider OAuth when mailbox access should be delegated through Google Workspace or Microsoft 365.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => handleOAuthConnect('google')}
            className="action-button-secondary disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={atCap}
            title={atCap ? 'Mailbox limit reached' : undefined}
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            Connect Google
          </button>
          <button
            type="button"
            onClick={() => handleOAuthConnect('microsoft')}
            className="action-button-secondary disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={atCap}
            title={atCap ? 'Mailbox limit reached' : undefined}
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            Connect Microsoft
          </button>
        </CardContent>
      </Card>

      {/* Fetch Schedule */}
      <div className="rounded-xl border bg-white shadow-sm p-6 mt-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-base font-semibold">Auto-Fetch Schedule</h3>
            <p className="text-sm text-slate-500 mt-0.5">Automatically fetch emails on a schedule</p>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" className="sr-only peer" checked={fetchEnabled} onChange={(e) => {
              const newValue = e.target.checked;
              setFetchEnabled(newValue);
              updateSettings.mutate({ fetch_emails_enabled: String(newValue) });
            }} />
            <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
          </label>
        </div>
        {fetchEnabled && (
          <div className="space-y-4 pt-2 border-t">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Interval</label>
                <select className="w-full rounded-lg border px-3 py-2 text-sm" value={fetchInterval} onChange={(e) => setFetchInterval(e.target.value)}>
                  <option value="5">Every 5 minutes</option>
                  <option value="10">Every 10 minutes</option>
                  <option value="15">Every 15 minutes</option>
                  <option value="30">Every 30 minutes</option>
                  <option value="60">Every hour</option>
                  <option value="120">Every 2 hours</option>
                  <option value="240">Every 4 hours</option>
                  <option value="480">Every 8 hours</option>
                  <option value="1440">Once daily</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Active days</label>
                <div className="flex flex-wrap gap-1">
                  {(['mon','tue','wed','thu','fri','sat','sun'] as const).map((day) => {
                    const active = fetchDays.split(',').map(d => d.trim()).includes(day);
                    return (
                      <button
                        key={day}
                        type="button"
                        onClick={() => {
                          const days = fetchDays.split(',').map(d => d.trim()).filter(Boolean);
                          const next = active ? days.filter(d => d !== day) : [...days, day];
                          setFetchDays(next.join(','));
                        }}
                        className={`px-2 py-1 rounded text-xs font-medium border ${active ? 'bg-primary text-white border-primary' : 'bg-white text-slate-600 border-slate-300'}`}
                      >
                        {day.charAt(0).toUpperCase() + day.slice(1)}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Start time</label>
                <input type="time" className="w-full rounded-lg border px-3 py-2 text-sm" value={fetchStartTime} onChange={(e) => setFetchStartTime(e.target.value)} />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">End time</label>
                <input type="time" className="w-full rounded-lg border px-3 py-2 text-sm" value={fetchEndTime} onChange={(e) => setFetchEndTime(e.target.value)} />
              </div>
            </div>
          </div>
        )}
        <div className="flex justify-end mt-4">
          <button
            className="px-4 py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary/90 disabled:opacity-50"
            disabled={updateSettings.isPending}
            onClick={() => {
              updateSettings.mutate({
                fetch_emails_enabled: String(fetchEnabled),
                fetch_emails_interval_minutes: fetchInterval,
                fetch_emails_days: fetchDays,
                fetch_emails_start_time: fetchStartTime,
                fetch_emails_end_time: fetchEndTime,
              }, { onSuccess: () => { setFetchSaved(true); setTimeout(() => setFetchSaved(false), 2000); } });
            }}
          >
            {fetchSaved ? 'Saved!' : 'Save Schedule'}
          </button>
        </div>
      </div>

      {isPanelOpen && (
        <div className="fixed inset-0 z-[90] bg-[rgba(0,0,0,0.15)]" onClick={() => setIsPanelOpen(false)}>
          <aside className="ml-auto h-full w-full max-w-[380px] overflow-y-auto bg-card p-6 shadow-[0_4px_16px_rgba(0,0,0,0.08)]" onClick={(event) => event.stopPropagation()}>
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-base font-semibold text-foreground">{editingMailbox ? `Edit ${editingMailbox.label}` : 'Create Mailbox'}</h2>
              <button type="button" className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-muted" onClick={() => setIsPanelOpen(false)}>
                <X className="h-4 w-4" />
              </button>
            </div>
            <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">Label</label>
              <input className="field-input" value={form.label} onChange={(event) => setForm((current) => ({ ...current, label: event.target.value }))} required />
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">Linked Client</label>
              <select className="field-input" value={form.linked_client_id} onChange={(event) => setForm((current) => ({ ...current, linked_client_id: event.target.value }))}>
                <option value="">No linked client</option>
                {clients.map((client: { id: number; name: string }) => (
                  <option key={client.id} value={client.id}>
                    {client.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">Protocol</label>
              <select className="field-input" value={form.protocol} onChange={(event) => setForm((current) => ({ ...current, protocol: event.target.value }))}>
                <option value="imap">IMAP</option>
                <option value="pop3">POP3</option>
                <option value="graph">Microsoft Graph</option>
              </select>
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">Authentication</label>
              <select className="field-input" value={form.auth_type} onChange={(event) => setForm((current) => ({ ...current, auth_type: event.target.value }))}>
                <option value="basic">Basic</option>
                <option value="oauth2">OAuth</option>
              </select>
            </div>
            <label className="flex items-center gap-3 rounded-2xl border border-border/70 bg-muted/20 px-4 py-3 text-sm">
              <input type="checkbox" checked={form.is_active} onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))} />
              Active mailbox
            </label>
          </div>

          {form.auth_type === 'basic' ? (
            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <label className="mb-2 block text-sm font-medium text-foreground">Host</label>
                <input className="field-input" value={form.host} onChange={(event) => setForm((current) => ({ ...current, host: event.target.value }))} required />
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium text-foreground">Port</label>
                <input className="field-input" value={form.port} onChange={(event) => setForm((current) => ({ ...current, port: event.target.value }))} />
              </div>
              <label className="flex items-center gap-3 rounded-2xl border border-border/70 bg-muted/20 px-4 py-3 text-sm">
                <input type="checkbox" checked={form.use_ssl} onChange={(event) => setForm((current) => ({ ...current, use_ssl: event.target.checked }))} />
                Use SSL
              </label>
            </div>
          ) : (
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">OAuth Provider</label>
              <select className="field-input" value={form.oauth_provider} onChange={(event) => setForm((current) => ({ ...current, oauth_provider: event.target.value as OAuthProvider | '' }))}>
                <option value="">Select provider</option>
                <option value="google">Google</option>
                <option value="microsoft">Microsoft</option>
              </select>
            </div>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">Username</label>
              <input className="field-input" value={form.username} onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))} />
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">Password / App Secret</label>
              <input type="password" className="field-input" value={form.password} onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))} />
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">SMTP Host</label>
              <input className="field-input" value={form.smtp_host} onChange={(event) => setForm((current) => ({ ...current, smtp_host: event.target.value }))} />
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">SMTP Port</label>
              <input className="field-input" value={form.smtp_port} onChange={(event) => setForm((current) => ({ ...current, smtp_port: event.target.value }))} />
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">SMTP Username</label>
              <input className="field-input" value={form.smtp_username} onChange={(event) => setForm((current) => ({ ...current, smtp_username: event.target.value }))} />
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">SMTP Password</label>
              <input type="password" className="field-input" value={form.smtp_password} onChange={(event) => setForm((current) => ({ ...current, smtp_password: event.target.value }))} />
            </div>
          </div>

          <div className="sticky bottom-0 flex justify-end gap-3 border-t border-border bg-card pt-3">
            <button type="button" onClick={() => setIsPanelOpen(false)} className="action-button-secondary">
              Cancel
            </button>
            <button type="submit" className="action-button" disabled={createMailbox.isPending || updateMailbox.isPending}>
              {createMailbox.isPending || updateMailbox.isPending ? 'Saving...' : editingMailbox ? 'Save Mailbox' : 'Create Mailbox'}
            </button>
          </div>
        </form>
          </aside>
        </div>
      )}
    </div>
  );
};
