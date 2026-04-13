import React from 'react';
import { ArrowRight, ChevronDown, ChevronRight, RefreshCw, ScanSearch, Search, Trash2 } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import axios from 'axios';


import { Badge, Loading } from '@/components';
import {
  useAuth,
  useClients,
  useDeleteIngestedEmail,
  useFetchJobStatus,
  useIngestionTimesheets,
  useReapplyIngestionMappings,
  useReprocessIngestionEmail,
  useReprocessSkippedEmails,
  useSkippedEmails,
  useTriggerFetchEmails,
} from '@/hooks';
import type { FetchMessageDiagnostic, IngestionTimesheetSummary, SkippedEmail } from '@/types';

const getApiErrorMessage = (error: unknown, fallback: string): string => {
  if (axios.isAxiosError(error) && typeof error.response?.data?.detail === 'string') {
    return error.response.data.detail;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
};

const formatShortDate = (value: string | null | undefined): string => {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

const formatDateRange = (start: string | null, end: string | null): string => {
  if (!start && !end) return '--';
  const startLabel = formatShortDate(start);
  const endLabel = formatShortDate(end);
  if (start && end) return `${startLabel} - ${endLabel}`;
  return startLabel !== '--' ? startLabel : endLabel;
};

const formatHours = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined || value === '') return '--';
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return String(value);
  return numeric.toFixed(1);
};

const cleanEmployeeNameForDisplay = (value?: string | null): string => {
  if (!value) return '';
  const compactLeadingPrefix = value.replace(/^ven[aij](?=[A-Z])/, '');
  const parts = compactLeadingPrefix.trim().split(/\s+/).filter(Boolean);
  if (parts.length > 1 && /^ven[aij]$/i.test(parts[0])) {
    parts.shift();
  }
  if (parts.length > 0 && /^ashw/i.test(parts[0])) {
    parts[0] = `Ai${parts[0].slice(1)}`;
  }
  return parts.join(' ').trim() || compactLeadingPrefix.trim();
};

const prettifySkipReason = (value: string | null | undefined): string => {
  if (!value) return 'Unknown reason';
  return value
    .replace(/^not_timesheet_email:/, 'not_timesheet_email ')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
};

const isNoiseSkipReason = (value: string | null | undefined): boolean => {
  if (!value) return false;
  return (
    value.startsWith('not_timesheet_email:') ||
    value.startsWith('low_confidence_no_attachments:') ||
    value === 'no_candidate_timesheet_attachment'
  );
};

const hasTimesheetKeywords = (value: string | null | undefined): boolean => {
  if (!value) return false;
  const text = value.toLowerCase();
  const keywords = [
    'timesheet',
    'time sheet',
    'timecard',
    'time card',
    'hours worked',
    'weekly hours',
    'work log',
    'billable',
  ];
  return keywords.some((keyword) => text.includes(keyword));
};

const isActionableSkippedEmail = (email: SkippedEmail): boolean => {
  if (isNoiseSkipReason(email.skip_reason)) return false;

  const hasTimesheetContext =
    hasTimesheetKeywords(email.subject) ||
    email.classification_intent === 'new_submission' ||
    email.classification_intent === 'resubmission' ||
    email.classification_intent === 'correction' ||
    email.classification_intent === 'submission' ||
    email.classification_intent === 'timesheet_submission' ||
    email.reprocessable_attachments.some((attachment) => hasTimesheetKeywords(attachment.filename));

  if (!hasTimesheetContext) return false;
  return email.timesheet_attachment_count > 0 || email.reprocessable_attachments.length > 0;
};

const isActionableDiagnostic = (message: FetchMessageDiagnostic): boolean => {
  if (!message.skipped) return true;
  if (isNoiseSkipReason(message.skip_reason)) return false;
  if (message.skip_reason === 'attachment_extraction_failed' || message.skip_reason === 'no_structured_timesheet_data') {
    return hasTimesheetKeywords(message.subject);
  }
  return true;
};

const getStatusTone = (status: string): 'success' | 'danger' | 'warning' | 'info' | 'outline' => {
  if (status === 'approved') return 'success';
  if (status === 'rejected') return 'danger';
  if (status === 'on_hold') return 'outline';
  if (status === 'under_review') return 'info';
  return 'warning';
};

const getPushTone = (pushStatus: string | null): 'success' | 'outline' => {
  return pushStatus === 'Sent' ? 'success' : 'outline';
};

const statusLabel = (status: string): string => {
  if (status === 'under_review') return 'Under Review';
  if (status === 'on_hold') return 'On Hold';
  return status.charAt(0).toUpperCase() + status.slice(1);
};

const STATUS_OPTIONS = [
  { key: '', label: 'All' },
  { key: 'pending', label: 'Pending' },
  { key: 'under_review', label: 'Under Review' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'on_hold', label: 'On Hold' },
];

const getStatusHeading = (tone: 'success' | 'danger' | 'info'): string => {
  if (tone === 'success') return 'Update complete';
  if (tone === 'danger') return 'Unable to complete that action';
  return 'Update in progress';
};

const getFriendlySystemMessage = (message: string | null | undefined, fallback: string): string => {
  if (!message) return fallback;
  if (message.includes('greenlet_spawn has not been called')) {
    return 'The fetch job failed before emails could be processed.';
  }
  if (message.includes('Email not found')) {
    return 'That email is no longer available.';
  }
  return message;
};

type TimesheetRowGroup = {
  key: string;
  status: string;
  timesheets: IngestionTimesheetSummary[];
  primary: IngestionTimesheetSummary;
  periods: number;
  totalHours: number;
  anomalyCount: number;
};

const buildRowGroups = (timesheets: IngestionTimesheetSummary[]): TimesheetRowGroup[] => {
  const map = new Map<string, TimesheetRowGroup>();

  for (const ts of timesheets) {
    // Group by attachment first: each attachment should represent one employee's source document.
    // This avoids OCR/name-variant splits (e.g. VENU/JHALAVYA spellings) creating duplicate rows.
    const extractedName = (ts.extracted_employee_name ?? ts.employee_name ?? '').toLowerCase().trim();
    const fallbackEmployeeKey = extractedName || (ts.employee_id != null ? String(ts.employee_id) : 'unassigned');
    const sourceKey = ts.attachment_id != null ? `att-${ts.attachment_id}` : `emp-${fallbackEmployeeKey}`;
    const key = `${ts.email_id}-${sourceKey}`;
    if (!map.has(key)) {
      map.set(key, {
        key,
        status: ts.status,
        timesheets: [ts],
        primary: ts,
        periods: 1,
        totalHours: Number(ts.total_hours ?? 0),
        anomalyCount: ts.llm_anomalies?.length ?? 0,
      });
      continue;
    }

    const group = map.get(key)!;
    const isDuplicatePeriod = group.timesheets.some((existing) => {
      const existingSignature = `${existing.attachment_id ?? 'no-att'}|${existing.period_start ?? ''}|${existing.period_end ?? ''}|${existing.total_hours ?? ''}`;
      const incomingSignature = `${ts.attachment_id ?? 'no-att'}|${ts.period_start ?? ''}|${ts.period_end ?? ''}|${ts.total_hours ?? ''}`;
      return existingSignature === incomingSignature;
    });
    if (isDuplicatePeriod) {
      continue;
    }
    group.timesheets.push(ts);
    group.periods += 1;
    group.totalHours += Number(ts.total_hours ?? 0);
    group.anomalyCount += ts.llm_anomalies?.length ?? 0;

    if (ts.status === 'pending' || group.status === 'pending') {
      group.status = 'pending';
    } else if (ts.status === 'under_review' || group.status === 'under_review') {
      group.status = 'under_review';
    } else if (ts.status === 'rejected' || group.status === 'rejected') {
      group.status = 'rejected';
    } else if (ts.status === 'on_hold' || group.status === 'on_hold') {
      group.status = 'on_hold';
    } else if (group.timesheets.every((item) => item.status === 'approved')) {
      group.status = 'approved';
    }
  }

  return Array.from(map.values()).map((group) => ({
    ...group,
    timesheets: [...group.timesheets].sort((left, right) => {
      const leftValue = left.period_start ? new Date(left.period_start).getTime() : Number.MAX_SAFE_INTEGER;
      const rightValue = right.period_start ? new Date(right.period_start).getTime() : Number.MAX_SAFE_INTEGER;
      return leftValue - rightValue;
    }),
  }));
};

const countStatuses = (groups: TimesheetRowGroup[]) =>
  STATUS_OPTIONS.reduce<Record<string, number>>((accumulator, option) => {
    if (!option.key) {
      accumulator[option.key] = groups.length;
      return accumulator;
    }
    accumulator[option.key] = groups.filter((group) => group.status === option.key).length;
    return accumulator;
  }, {});

export const InboxPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const [activeJobId, setActiveJobId] = React.useState<string | null>(null);
  const [statusFilter, setStatusFilter] = React.useState('');
  const [clientId, setClientId] = React.useState('');
  const [search, setSearch] = React.useState('');
  const [statusMessage, setStatusMessage] = React.useState<string | null>(null);
  const [statusTone, setStatusTone] = React.useState<'success' | 'danger' | 'info'>('info');

  const [showDiagnostics, setShowDiagnostics] = React.useState(false);
  const [showMoreActions, setShowMoreActions] = React.useState(false);
  const [showTechnicalDetails, setShowTechnicalDetails] = React.useState(false);

  const queryClient = useQueryClient();
  const triggerFetch = useTriggerFetchEmails();
  const reprocessSkipped = useReprocessSkippedEmails();
  const reprocessEmail = useReprocessIngestionEmail();
  const deleteEmail = useDeleteIngestedEmail();
  const reapplyMappings = useReapplyIngestionMappings();
  const { data: fetchStatus } = useFetchJobStatus(activeJobId, Boolean(activeJobId));

  // When job completes, refresh the inbox and skipped lists
  React.useEffect(() => {
    if (fetchStatus?.status === 'complete') {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'skipped-emails'] });
      setStatusTone('success');
      setStatusMessage(fetchStatus.message || 'Fetch complete.');
      setActiveJobId(null);
    } else if (fetchStatus?.status === 'failed') {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'skipped-emails'] });
      setStatusTone('danger');
      setStatusMessage(fetchStatus.message || 'Fetch job failed.');
      setActiveJobId(null);
    }
  }, [fetchStatus?.status, fetchStatus?.message, queryClient]);
  const { data: clients = [] } = useClients();
  const { data: skippedOverview, isLoading: skippedLoading } = useSkippedEmails(8);
  const { data: allTimesheets = [], isLoading: countsLoading } = useIngestionTimesheets(
    { limit: 200 },
    true,
  );
  const { data: timesheets = [], isLoading } = useIngestionTimesheets({
    status_filter: statusFilter || undefined,
    client_id: clientId ? Number(clientId) : undefined,
    search: search.trim() || undefined,
    limit: 200,
  });

  const isPageLoading = isLoading || countsLoading || skippedLoading;
  const allGroups = React.useMemo(() => buildRowGroups(allTimesheets), [allTimesheets]);
  const groups = React.useMemo(() => buildRowGroups(timesheets), [timesheets]);
  const statusCounts = React.useMemo(() => countStatuses(allGroups), [allGroups]);
  const fetchDiagnostics = React.useMemo<FetchMessageDiagnostic[]>(() => {
    const diagnostics = fetchStatus?.result && typeof fetchStatus.result === 'object' && 'message_diagnostics' in fetchStatus.result
      ? fetchStatus.result.message_diagnostics
      : [];
    if (!Array.isArray(diagnostics)) return [];
    return diagnostics
      .filter((item): item is FetchMessageDiagnostic => Boolean(item && typeof item === 'object'))
      .filter(isActionableDiagnostic)
      .slice(0, 8);
  }, [fetchStatus]);

  const actionableSkippedEmails = React.useMemo(() => {
    const rows = skippedOverview?.emails ?? [];
    return rows.filter(isActionableSkippedEmail);
  }, [skippedOverview]);

  if (isPageLoading) {
    return <Loading message="Loading reviewer inbox..." />;
  }

  const isFetchRunning = Boolean(
    activeJobId && fetchStatus && (fetchStatus.status === 'queued' || fetchStatus.status === 'in_progress'),
  );
  const isBusy =
    triggerFetch.isPending ||
    isFetchRunning ||
    reprocessSkipped.isPending ||
    reprocessEmail.isPending ||
    deleteEmail.isPending ||
    reapplyMappings.isPending;

  const handleFetch = async () => {
    try {
      const response = await triggerFetch.mutateAsync();
      setActiveJobId(response.job_id);
      setStatusTone('info');
      setStatusMessage(response.message || 'Fetch job queued for this tenant.');
    } catch (error) {
      setStatusTone('danger');
      setStatusMessage(getApiErrorMessage(error, 'Unable to start fetch job.'));
    }
  };

  const handleReprocessSkipped = async () => {
    if (!window.confirm('Reprocess stored skipped emails for this tenant? This keeps the ingested emails in place and re-runs extraction.')) {
      return;
    }

    try {
      const response = await reprocessSkipped.mutateAsync();
      setActiveJobId(response.job_id);
      setStatusTone('info');
      setStatusMessage('Queued stored skipped emails for reprocessing.');
    } catch (error) {
      setStatusTone('danger');
      setStatusMessage(getApiErrorMessage(error, 'Unable to reprocess skipped emails.'));
    }
  };

  const handleReprocessEmail = async (emailId: number, attachmentIds?: number[]) => {
    try {
      const response = await reprocessEmail.mutateAsync({ emailId, attachmentIds });
      setActiveJobId(response.job_id);
      setStatusTone('info');
      setStatusMessage(
        response.mode === 'reprocess_attachments'
          ? 'Queued attachment-only reprocessing.'
          : 'Queued email reprocessing.',
      );
    } catch (error) {
      setStatusTone('danger');
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        setStatusMessage('That inbox item is no longer available. The list has been refreshed.');
        return;
      }
      setStatusMessage(getApiErrorMessage(error, 'Unable to queue reprocessing.'));
    }
  };

  const handleDeleteEmail = async (emailId: number, subject?: string | null, refetch: boolean = false) => {
    const action = refetch ? 'Delete & re-fetch' : 'Delete';
    const suffix = refetch ? ' The next Fetch Emails will re-ingest it.' : ' This does not remove the original mailbox email.';
    if (!window.confirm(`${action} "${subject || '(no subject)'}" from this application?${suffix}`)) {
      return;
    }
    try {
      await deleteEmail.mutateAsync({ emailId, refetch });
      setStatusTone('success');
      setStatusMessage(
        refetch
          ? 'Removed stored email. Click "Fetch Emails" to re-ingest it from the mailbox.'
          : 'Removed stored email and derived staged records from this app.',
      );
    } catch (error) {
      setStatusTone('danger');
      setStatusMessage(getApiErrorMessage(error, 'Unable to delete stored email.'));
    }
  };

  const handleReapplyMappings = async () => {
    try {
      const result = await reapplyMappings.mutateAsync();
      setStatusTone('success');
      setStatusMessage(`Re-applied mappings across ${result.checked} staged timesheets. Updated ${result.updated}.`);
    } catch (error) {
      setStatusTone('danger');
      setStatusMessage(getApiErrorMessage(error, 'Unable to re-apply mappings.'));
    }
  };

  const progress = Math.max(0, Math.min(100, Number(fetchStatus?.progress ?? 0)));
  const fetchStatusTone =
    fetchStatus?.status === 'complete' ? 'success' : fetchStatus?.status === 'failed' ? 'danger' : 'info';
  const showStandaloneStatusMessage =
    Boolean(statusMessage) &&
    (!fetchStatus || fetchStatus.status === 'not_found' || statusTone !== 'info');
  const locationBanner =
    typeof location.state === 'object' && location.state !== null && 'banner' in location.state && typeof location.state.banner === 'string'
      ? location.state.banner
      : null;
  const hasAnyQueueItems = allGroups.length > 0;
  const hasActiveFilters = Boolean(statusFilter || clientId || search.trim());
  const showFilters = hasAnyQueueItems || hasActiveFilters;
  const fetchStatusMessage = getFriendlySystemMessage(fetchStatus?.message, 'Waiting for worker status...');
  const rawFetchStatusMessage = fetchStatus?.message || '';
  const hasTechnicalDetails = Boolean(rawFetchStatusMessage) && rawFetchStatusMessage !== fetchStatusMessage;
  const showActivityStrip =
    (activeJobId && fetchStatus && fetchStatus.status !== 'not_found') ||
    showStandaloneStatusMessage ||
    Boolean(locationBanner) ||
    fetchDiagnostics.length > 0;
  const clearFilters = () => {
    setStatusFilter('');
    setClientId('');
    setSearch('');
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-start">
        <div>
          <h1 className="text-[20px] font-semibold text-foreground">Inbox</h1>
          <p className="mt-2 text-sm text-muted-foreground">Review and process incoming timesheets.</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowMoreActions((current) => !current)}
              className="action-button-secondary"
              disabled={isBusy}
            >
              More Actions
              <ChevronDown className="ml-2 h-4 w-4" />
            </button>
            {showMoreActions ? (
              <div className="absolute right-0 top-[calc(100%+8px)] z-20 min-w-[220px] rounded-xl border border-border bg-background p-2 shadow-lg">
                <button
                  type="button"
                  onClick={() => {
                    setShowMoreActions(false);
                    void handleReapplyMappings();
                  }}
                  className="flex w-full items-center rounded-lg px-3 py-2 text-left text-sm text-foreground transition hover:bg-muted"
                >
                  <RefreshCw className="mr-2 h-4 w-4" />
                  {reapplyMappings.isPending ? 'Applying mappings...' : 'Re-apply mappings'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowMoreActions(false);
                    void handleReprocessSkipped();
                  }}
                  className="flex w-full items-center rounded-lg px-3 py-2 text-left text-sm text-foreground transition hover:bg-muted"
                >
                  <ScanSearch className="mr-2 h-4 w-4" />
                  {reprocessSkipped.isPending ? 'Queueing skipped emails...' : 'Reprocess skipped emails'}
                </button>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={handleFetch}
            className="action-button"
            disabled={isBusy}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${(triggerFetch.isPending || isFetchRunning) ? 'animate-spin' : ''}`} />
            {triggerFetch.isPending ? 'Starting Fetch...' : isFetchRunning ? 'Fetching Emails...' : 'Fetch Emails'}
          </button>
        </div>
      </div>

      {showActivityStrip ? (
        <section className="surface-card px-5 py-3">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
            <div className="space-y-2">
              <div>
                <p className="text-sm font-semibold text-foreground">Recent activity</p>
                <p className="mt-0.5 text-xs text-muted-foreground">Background jobs and recent actions.</p>
              </div>

              {activeJobId && fetchStatus && fetchStatus.status !== 'not_found' ? (
                <div className="rounded-2xl border border-border/60 bg-muted/35 px-4 py-2.5">
                  <div className="flex flex-wrap items-center gap-3">
                    <Badge tone={fetchStatusTone} className="normal-case tracking-normal">
                      {fetchStatus.status}
                    </Badge>
                    {fetchStatus.mode ? (
                      <span className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                        {fetchStatus.mode.replace(/_/g, ' ')}
                      </span>
                    ) : null}
                    <span className="font-mono text-[11px] text-muted-foreground">{activeJobId}</span>
                  </div>
                  <p className="mt-2 text-sm text-foreground">{fetchStatusMessage}</p>
                  {hasTechnicalDetails ? (
                    <button
                      type="button"
                      onClick={() => setShowTechnicalDetails((current) => !current)}
                      className="mt-2 text-xs font-medium text-muted-foreground transition hover:text-foreground"
                    >
                      {showTechnicalDetails ? 'Hide technical details' : 'Show technical details'}
                    </button>
                  ) : null}
                  {hasTechnicalDetails && showTechnicalDetails ? (
                    <p className="mt-2 rounded-xl bg-background px-3 py-2 font-mono text-xs text-muted-foreground">
                      {rawFetchStatusMessage}
                    </p>
                  ) : null}
                  {(fetchStatus.status === 'queued' || fetchStatus.status === 'in_progress') ? (
                    <div className="mt-2 space-y-1.5">
                      <div className="h-2 overflow-hidden rounded-full bg-background">
                        <div className="h-full rounded-full bg-amber-300 transition-all duration-300" style={{ width: `${progress}%` }} />
                      </div>
                      <div className="flex items-center justify-between text-xs uppercase tracking-[0.16em] text-muted-foreground">
                        <span>Worker progress</span>
                        <span>{progress}%</span>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {locationBanner ? (
                <p className="text-sm text-emerald-700">{locationBanner}</p>
              ) : null}

              {showStandaloneStatusMessage ? (
                <div>
                  <p className="text-sm font-semibold text-foreground">{getStatusHeading(statusTone)}</p>
                  <p className="mt-1 text-sm text-muted-foreground">{statusMessage}</p>
                </div>
              ) : null}
            </div>

            {(fetchStatus?.result || fetchDiagnostics.length > 0) ? (
              <div className="min-w-[220px] space-y-2 rounded-2xl border border-border/60 bg-background px-4 py-2.5">
                {fetchStatus?.result ? (
                  <div className="grid grid-cols-3 gap-3 text-center">
                    <div>
                      <p className="text-lg font-semibold text-foreground">{String(fetchStatus.result.total_fetched ?? 0)}</p>
                      <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Fetched</p>
                    </div>
                    <div>
                      <p className="text-lg font-semibold text-foreground">{String(fetchStatus.result.total_timesheets_created ?? 0)}</p>
                      <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Staged</p>
                    </div>
                    <div>
                      <p className="text-lg font-semibold text-foreground">{String(fetchStatus.result.total_skipped ?? 0)}</p>
                      <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Skipped</p>
                    </div>
                  </div>
                ) : null}
                {fetchDiagnostics.length > 0 ? (
                  <button
                    type="button"
                    onClick={() => setShowDiagnostics((current) => !current)}
                    className="flex w-full items-center justify-between rounded-xl bg-muted/40 px-3 py-2 text-left text-sm text-foreground transition hover:bg-muted"
                  >
                    <span>Latest fetch diagnostics</span>
                    {showDiagnostics ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      {showDiagnostics && fetchDiagnostics.length > 0 ? (
        <section className="surface-card px-5 py-4">
          <div className="space-y-2">
            {fetchDiagnostics.map((message, index) => {
              const canInspect = Boolean(message.email_id);
              return (
                <div
                  key={`${message.email_id ?? message.message_id ?? 'message'}-${index}`}
                  className={[
                    'rounded-2xl border border-border/50 bg-white/[0.02] px-4 py-3 transition',
                    canInspect ? 'cursor-pointer hover:border-amber-300/30 hover:bg-white/[0.04]' : '',
                  ].join(' ')}
                  onClick={() => {
                    if (!message.email_id) return;
                    navigate(`/ingestion/email/${message.email_id}`);
                  }}
                  onKeyDown={(event) => {
                    if (!message.email_id) return;
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      navigate(`/ingestion/email/${message.email_id}`);
                    }
                  }}
                  role={canInspect ? 'button' : undefined}
                  tabIndex={canInspect ? 0 : -1}
                >
                  <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="font-medium text-foreground">{message.subject || 'No subject'}</p>
                      <p className="text-sm text-muted-foreground">{message.sender_email || 'Unknown sender'}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {message.skipped ? (
                        <Badge tone="warning" className="normal-case tracking-normal">
                          {prettifySkipReason(message.skip_reason)}
                        </Badge>
                      ) : (
                        <Badge tone="success" className="normal-case tracking-normal">
                          {message.timesheets_created ? `${message.timesheets_created} staged` : 'Processed'}
                        </Badge>
                      )}
                    </div>
                  </div>
                  {message.skip_detail ? <p className="mt-2 text-sm text-muted-foreground">{message.skip_detail}</p> : null}
                  {message.errors?.length ? <p className="mt-2 text-sm text-amber-700">{message.errors[0]}</p> : null}
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      <section className="surface-card overflow-hidden">
        <div className="border-b border-border/70 px-5 py-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-base font-semibold text-foreground">Review queue</h2>
                <Badge tone="outline" className="normal-case tracking-normal">
                  {groups.length} showing
                </Badge>
                {hasAnyQueueItems ? (
                  <span className="text-sm text-muted-foreground">{allGroups.length} grouped submissions ready for review</span>
                ) : null}
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                Open a submission directly, or expand grouped emails to choose a specific week.
              </p>
            </div>
            {showFilters ? (
              <button
                type="button"
                onClick={clearFilters}
                className="text-sm font-medium text-muted-foreground transition hover:text-foreground"
              >
                Reset filters
              </button>
            ) : null}
          </div>
        </div>

        {showFilters ? (
          <div className="space-y-4 border-b border-border/70 bg-muted/20 px-5 py-4">
            <div className="flex flex-wrap gap-2">
              {STATUS_OPTIONS.map((option) => {
                const active = statusFilter === option.key;
                const count = statusCounts[option.key] ?? 0;
                return (
                  <button
                    key={option.key || 'all'}
                    type="button"
                    onClick={() => setStatusFilter(option.key)}
                    className={[
                      'inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition',
                      active
                        ? 'bg-[var(--accent-light)] text-primary'
                        : 'bg-transparent text-muted-foreground hover:bg-muted hover:text-foreground',
                    ].join(' ')}
                  >
                    <span>{option.label}</span>
                    <span className="rounded-full px-2 py-0.5 text-[11px]">{count}</span>
                  </button>
                );
              })}
            </div>

            <div className="flex flex-col gap-3 md:flex-row">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <input
                  className="field-input pl-11"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search by sender or subject..."
                />
              </div>
              <select className="field-input md:max-w-xs" value={clientId} onChange={(event) => setClientId(event.target.value)}>
                <option value="">All Clients</option>
                {clients.map((client: { id: number; name: string }) => (
                  <option key={client.id} value={client.id}>
                    {client.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        ) : null}

        <div className="overflow-x-auto">
          {groups.length === 0 ? (
            <div className="px-6 py-12">
              <div className="mx-auto max-w-xl rounded-3xl border border-dashed border-border/70 bg-card/60 px-8 py-12 text-center">
                <p className="text-lg font-semibold text-foreground">
                  {hasActiveFilters ? 'No submissions match the current filters.' : 'No staged timesheets to review.'}
                </p>
                <p className="mt-3 text-sm text-muted-foreground">
                  {hasActiveFilters
                    ? 'Clear the current filters to return to the full review queue.'
                    : 'Fetch new emails to create staged timesheets, or review skipped emails if any need attention.'}
                </p>
                <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
                  {!hasActiveFilters ? (
                    <button type="button" onClick={handleFetch} className="action-button" disabled={isBusy}>
                      <RefreshCw className={`mr-2 h-4 w-4 ${(triggerFetch.isPending || isFetchRunning) ? 'animate-spin' : ''}`} />
                      {triggerFetch.isPending ? 'Starting Fetch...' : isFetchRunning ? 'Fetching Emails...' : 'Fetch Emails'}
                    </button>
                  ) : null}
                  {hasActiveFilters ? (
                    <button type="button" onClick={clearFilters} className="action-button-secondary">
                      Reset filters
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          ) : (
            <table className="min-w-full text-left">
              <thead className="border-b border-border">
                <tr className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                  <th className="px-4 py-4 font-medium">Sender</th>
                  <th className="px-4 py-4 font-medium">Subject</th>
                  <th className="px-4 py-4 font-medium">Client</th>
                  <th className="px-4 py-4 font-medium">Employee</th>
                  <th className="px-4 py-4 font-medium">Week</th>
                  <th className="px-4 py-4 font-medium">Hours</th>
                  <th className="px-4 py-4 font-medium">Status</th>
                  <th className="px-4 py-4 font-medium">Push</th>
                  <th className="px-4 py-4 font-medium">AI Flags</th>
                  <th className="px-4 py-4 font-medium">Received</th>
                  <th className="px-4 py-4 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => {
                  const isMultiPeriod = group.periods > 1;
                  const rowTarget = group.primary;
                  const canOpenReview = Number.isInteger(rowTarget.id) && rowTarget.id > 0;

                  return (
                    <React.Fragment key={group.key}>
                      <tr
                        className={`group h-11 transition hover:bg-muted ${canOpenReview ? 'cursor-pointer' : 'cursor-default'}`}
                        onClick={() => {
                          if (!canOpenReview) return;
                          navigate(`/ingestion/review/${rowTarget.id}`);
                        }}
                      >
                        <td className="px-4 py-5 align-top">
                          <div className="flex min-w-[180px] items-start gap-3">

                            <div>
                              <p className="font-semibold text-foreground">
                                {rowTarget.sender_name || rowTarget.sender_email || 'Unknown sender'}
                                {rowTarget.is_likely_resubmission && (
                                  <span
                                    className="inline-flex px-1.5 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-700 ml-1"
                                    title="A rejected submission from this sender exists for a similar period. Review and delete the old rejected record after approving this one."
                                  >
                                    Possible resubmission
                                  </span>
                                )}
                              </p>
                              <p className="mt-1 font-mono text-xs text-muted-foreground">{rowTarget.sender_email || '--'}</p>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-5 align-top">
                          <div className="min-w-[200px] space-y-2">
                            <p className="font-medium text-foreground">{rowTarget.subject || 'No subject'}</p>
                            {isMultiPeriod ? (
                              <Badge tone="info" className="normal-case tracking-normal">
                                {group.periods} weeks
                              </Badge>
                            ) : null}
                          </div>
                        </td>
                        <td className="px-4 py-5 align-top text-sm text-foreground">
                          {rowTarget.client_name || '--'}
                        </td>
                        <td className="px-4 py-5 align-top">
                          {rowTarget.extracted_employee_name || rowTarget.employee_name ? (
                            <span className="text-sm text-foreground">
                              {cleanEmployeeNameForDisplay(rowTarget.extracted_employee_name || rowTarget.employee_name)}
                            </span>
                          ) : (
                            <span className="text-sm italic text-muted-foreground">Unassigned</span>
                          )}
                        </td>
                        <td className="px-4 py-5 align-top text-sm text-muted-foreground">
                          {isMultiPeriod
                            ? formatDateRange(group.timesheets[0]?.period_start ?? null, group.timesheets[group.timesheets.length - 1]?.period_end ?? null)
                            : formatDateRange(rowTarget.period_start, rowTarget.period_end)}
                        </td>
                        <td className="px-4 py-5 align-top font-mono text-sm font-medium text-foreground">
                          {formatHours(group.totalHours)}
                        </td>
                        <td className="px-4 py-5 align-top">
                          <Badge tone={getStatusTone(group.status)} className="normal-case tracking-normal">
                            {statusLabel(group.status)}
                          </Badge>
                        </td>
                        <td className="px-4 py-5 align-top">
                          <Badge tone={getPushTone(rowTarget.push_status)} className="normal-case tracking-normal">
                            {rowTarget.push_status || 'Not sent'}
                          </Badge>
                        </td>
                        <td className="px-4 py-5 align-top text-sm text-muted-foreground">
                          {group.anomalyCount ? `${group.anomalyCount}` : '--'}
                        </td>
                        <td className="px-4 py-5 align-top text-sm text-muted-foreground">
                          {formatShortDate(rowTarget.received_at || rowTarget.created_at)}
                        </td>
                        <td className="px-4 py-5 align-top text-right">
                          <div className="flex justify-end gap-2 opacity-0 transition group-hover:opacity-100">
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                const attachmentIds = group.timesheets
                                  .map((timesheet) => timesheet.attachment_id)
                                  .filter((attachmentId): attachmentId is number => Boolean(attachmentId));
                                void handleReprocessEmail(rowTarget.email_id, attachmentIds.length ? attachmentIds : undefined);
                              }}
                              className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-muted text-foreground transition hover:bg-slate-200"
                              aria-label={`Reprocess email ${rowTarget.email_id}`}
                            >
                              <RefreshCw className="h-4 w-4" />
                            </button>
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                void handleDeleteEmail(rowTarget.email_id, rowTarget.subject);
                              }}
                              className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-muted text-foreground transition hover:bg-red-50 hover:text-red-700"
                              aria-label={`Delete email ${rowTarget.email_id}`}
                              title="Delete"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                void handleDeleteEmail(rowTarget.email_id, rowTarget.subject, true);
                              }}
                              className="inline-flex h-7 items-center justify-center rounded-md bg-muted px-1.5 text-[10px] font-medium text-foreground transition hover:bg-amber-50 hover:text-amber-700"
                              aria-label={`Delete and refetch email ${rowTarget.email_id}`}
                              title="Delete & re-fetch on next Fetch Emails"
                            >
                              Re-fetch
                            </button>
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                if (!canOpenReview) return;
                                navigate(`/ingestion/review/${rowTarget.id}`);
                              }}
                              className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-muted text-foreground transition hover:bg-slate-200"
                              aria-label={`Open submission ${rowTarget.id}`}
                              disabled={!canOpenReview}
                            >
                              <ArrowRight className="h-4 w-4" />
                            </button>
                          </div>
                        </td>
                      </tr>

                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {actionableSkippedEmails.length > 0 ? (
        <section className="surface-card px-5 py-5">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <div className="flex items-center gap-3">
                <p className="text-base font-semibold text-foreground">Skipped Emails</p>
                <Badge tone="warning" className="normal-case tracking-normal">
                  {actionableSkippedEmails.length}
                </Badge>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                These emails look relevant but still need a manual reprocess or cleanup step.
              </p>
            </div>
          </div>

          <div className="mt-4 space-y-3">
            {actionableSkippedEmails.map((email) => (
              <div key={email.id} className="rounded-md bg-muted/60 px-4 py-4">
                <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium text-foreground">{email.subject || 'No subject'}</p>
                      {email.mailbox_label && <Badge tone="outline">{email.mailbox_label}</Badge>}
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {email.sender_name || email.sender_email} · {email.sender_email} · {formatShortDate(email.received_at)}
                    </p>
                    <div className="flex flex-wrap items-center gap-3 text-xs uppercase tracking-[0.18em] text-muted-foreground">
                      <span>{email.timesheet_attachment_count} candidate attachment{email.timesheet_attachment_count === 1 ? '' : 's'}</span>
                      <span>{prettifySkipReason(email.skip_reason)}</span>
                    </div>
                    {email.skip_detail && <p className="text-sm text-muted-foreground">{email.skip_detail}</p>}
                    {!!email.reprocessable_attachments.length && (
                      <p className="text-sm text-muted-foreground">
                        Attachments: {email.reprocessable_attachments.map((attachment) => attachment.filename).join(', ')}
                      </p>
                    )}
                  </div>

                  <div className="flex shrink-0 flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={() => handleReprocessEmail(email.id)}
                      className="action-button-secondary"
                      disabled={isBusy}
                    >
                      <RefreshCw className="mr-2 h-4 w-4" />
                      Reprocess
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteEmail(email.id, email.subject)}
                      className="action-button-secondary"
                      disabled={isBusy}
                    >
                      <Trash2 className="mr-2 h-4 w-4" />
                      Delete
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteEmail(email.id, email.subject, true)}
                      className="action-button-secondary"
                      disabled={isBusy}
                    >
                      <RefreshCw className="mr-2 h-4 w-4" />
                      Delete &amp; Re-fetch
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
};
