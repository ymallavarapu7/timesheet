import React, { useState } from 'react';
import { ArrowRight, ChevronDown, ChevronRight, RefreshCw, Search, Trash2 } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import axios from 'axios';


import { Badge, Loading } from '@/components';
import { BulkSelectBar } from '@/components/ui/BulkSelectBar';
import {
  useAuth,
  useBulkReprocessEmails,
  useBulkDeleteIngestedEmails,
  useClients,
  useDeleteIngestedEmail,
  useFetchJobStatus,
  useIngestionTimesheets,
  useMailboxes,
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
  // Pick up job ID from navigation state (e.g., after reprocess from review panel)
  const navJobId =
    typeof location.state === 'object' && location.state !== null && 'jobId' in location.state && typeof location.state.jobId === 'string'
      ? location.state.jobId
      : null;
  const [activeJobId, setActiveJobId] = React.useState<string | null>(navJobId);
  const [statusFilter, setStatusFilter] = React.useState('');
  const [clientId, setClientId] = React.useState('');
  const [search, setSearch] = React.useState('');
  const [statusMessage, setStatusMessage] = React.useState<string | null>(null);
  const [statusTone, setStatusTone] = React.useState<'success' | 'danger' | 'info'>('info');

  const [showDiagnostics, setShowDiagnostics] = React.useState(false);
  const [showTechnicalDetails, setShowTechnicalDetails] = React.useState(false);
  const [selectedEmailIds, setSelectedEmailIds] = useState<Set<number>>(new Set());

  const queryClient = useQueryClient();
  const triggerFetch = useTriggerFetchEmails();
  const { data: mailboxes = [] } = useMailboxes();
  const lastFetchedAt = React.useMemo(() => {
    const stamps = mailboxes
      .map((m) => m.last_fetched_at)
      .filter((s): s is string => Boolean(s))
      .map((s) => new Date(s).getTime())
      .filter((n) => Number.isFinite(n));
    if (stamps.length === 0) return null;
    return new Date(Math.max(...stamps));
  }, [mailboxes]);
  const reprocessSkipped = useReprocessSkippedEmails();
  const reprocessEmail = useReprocessIngestionEmail();
  const deleteEmail = useDeleteIngestedEmail();
  const bulkReprocessEmails = useBulkReprocessEmails();
  const bulkDeleteEmails = useBulkDeleteIngestedEmails();
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

  // Clear bulk selection when the underlying data refreshes
  React.useEffect(() => {
    setSelectedEmailIds(new Set());
  }, [timesheets]);

  // Collect unique email_ids from currently visible groups
  const allVisibleEmailIds = React.useMemo(
    () => [...new Set(groups.map((group) => group.primary.email_id))],
    [groups],
  );

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
    bulkReprocessEmails.isPending ||
    bulkDeleteEmails.isPending;

  const handleBulkReprocess = async () => {
    const ids = [...selectedEmailIds];
    if (ids.length === 0) return;
    if (!window.confirm(`Reprocess ${ids.length} email(s)? This will re-run extraction and matching.`)) return;
    try {
      const result = await bulkReprocessEmails.mutateAsync(ids);
      setSelectedEmailIds(new Set());
      setStatusTone('success');
      setStatusMessage(`Queued ${result.queued} email(s) for reprocessing.`);
    } catch {
      setStatusTone('danger');
      setStatusMessage('Failed to queue bulk reprocess.');
    }
  };

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
      if (refetch) {
        setStatusTone('info');
        setStatusMessage('Email removed. Fetching fresh copy from mailbox...');
        try {
          const response = await triggerFetch.mutateAsync();
          setActiveJobId(response.job_id);
        } catch {
          setStatusTone('success');
          setStatusMessage('Email removed. Auto-fetch failed — click "Fetch Emails" to re-ingest manually.');
        }
      } else {
        setStatusTone('success');
        setStatusMessage('Removed stored email and derived staged records.');
      }
    } catch (error) {
      setStatusTone('danger');
      setStatusMessage(getApiErrorMessage(error, 'Unable to delete stored email.'));
    }
  };

  const toggleEmailId = (emailId: number) => {
    setSelectedEmailIds((prev) => {
      const next = new Set(prev);
      if (next.has(emailId)) {
        next.delete(emailId);
      } else {
        next.add(emailId);
      }
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelectedEmailIds(new Set(allVisibleEmailIds));
  };

  const clearSelection = () => {
    setSelectedEmailIds(new Set());
  };

  const handleBulkDelete = async () => {
    const ids = [...selectedEmailIds];
    if (ids.length === 0) return;
    if (!window.confirm(`Delete ${ids.length} email(s) and all their staged timesheets from this application?`)) {
      return;
    }
    try {
      await bulkDeleteEmails.mutateAsync(ids);
      setSelectedEmailIds(new Set());
      setStatusTone('success');
      setStatusMessage(`Deleted ${ids.length} email(s) and their staged records.`);
    } catch (error) {
      setStatusTone('danger');
      setStatusMessage(getApiErrorMessage(error, 'Unable to bulk delete emails.'));
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
  const fetchStatusMessage = getFriendlySystemMessage(fetchStatus?.message, 'Starting up...');
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
          <p className="mt-2 text-sm text-muted-foreground">
            Review and process incoming timesheets.
            {lastFetchedAt && (
              <>
                {' '}<span className="text-muted-foreground/80">· Last fetched {lastFetchedAt.toLocaleString()}</span>
              </>
            )}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
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
            <div className="flex-1 space-y-2">

              {activeJobId && fetchStatus && fetchStatus.status !== 'not_found' ? (
                <div className="flex items-center gap-3">
                  <Badge tone={fetchStatusTone} className="normal-case tracking-normal">
                    {fetchStatus.status === 'queued' ? 'Queued' :
                     fetchStatus.status === 'in_progress' ? 'Processing' :
                     fetchStatus.status === 'complete' ? 'Complete' :
                     fetchStatus.status === 'failed' ? 'Failed' :
                     fetchStatus.status}
                  </Badge>
                  <span className="text-sm text-foreground">{fetchStatusMessage}</span>
                  {(fetchStatus.status === 'queued' || fetchStatus.status === 'in_progress') ? (
                    <div className="flex items-center gap-2 flex-1 max-w-xs">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-background">
                        <div className="h-full rounded-full bg-primary/60 transition-all duration-300" style={{ width: `${progress}%` }} />
                      </div>
                      <span className="text-xs text-muted-foreground">{progress}%</span>
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

        {selectedEmailIds.size > 0 && (
          <div className="border-b border-border/70 px-5 py-3">
            <div className="flex items-center justify-between gap-4 rounded-lg border border-primary/20 bg-primary/5 px-4 py-2.5">
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium text-foreground">
                  {selectedEmailIds.size} email{selectedEmailIds.size !== 1 ? 's' : ''} selected
                </span>
                {selectedEmailIds.size < allVisibleEmailIds.length && (
                  <button type="button" onClick={selectAllVisible} className="text-xs font-medium text-primary hover:text-primary/80 transition">
                    Select all {allVisibleEmailIds.length}
                  </button>
                )}
                <button type="button" onClick={clearSelection} className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground transition">
                  Clear
                </button>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleBulkReprocess}
                  disabled={isBusy}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary transition hover:bg-primary/20 disabled:opacity-50"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${bulkReprocessEmails.isPending ? 'animate-spin' : ''}`} />
                  {bulkReprocessEmails.isPending ? 'Queueing...' : `Reprocess ${selectedEmailIds.size}`}
                </button>
                <button
                  type="button"
                  onClick={handleBulkDelete}
                  disabled={isBusy}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-destructive px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-destructive/90 disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {bulkDeleteEmails.isPending ? 'Deleting...' : `Delete ${selectedEmailIds.size}`}
                </button>
              </div>
            </div>
          </div>
        )}

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
                  <th className="w-10 px-2 py-4">
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-border accent-primary"
                      checked={allVisibleEmailIds.length > 0 && allVisibleEmailIds.every((id) => selectedEmailIds.has(id))}
                      onChange={(event) => {
                        if (event.target.checked) {
                          selectAllVisible();
                        } else {
                          clearSelection();
                        }
                      }}
                    />
                  </th>
                  <th className="px-4 py-4 font-medium">Sender</th>
                  <th className="px-4 py-4 font-medium">Subject</th>
                  <th className="px-4 py-4 font-medium">Client</th>
                  <th className="px-4 py-4 font-medium">Employee</th>
                  <th className="px-4 py-4 font-medium">Week</th>
                  <th className="px-4 py-4 font-medium">Hours</th>
                  <th className="px-4 py-4 font-medium">Status</th>
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
                        <td className="w-10 px-2 py-5 align-top">
                          <input
                            type="checkbox"
                            className="h-4 w-4 rounded border-border accent-primary"
                            checked={selectedEmailIds.has(rowTarget.email_id)}
                            onClick={(event) => event.stopPropagation()}
                            onChange={() => toggleEmailId(rowTarget.email_id)}
                          />
                        </td>
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
                        <td className="px-4 py-5 align-top text-sm text-muted-foreground">
                          {group.anomalyCount ? `${group.anomalyCount}` : '--'}
                        </td>
                        <td className="px-4 py-5 align-top text-sm text-muted-foreground">
                          {formatShortDate(rowTarget.received_at || rowTarget.created_at)}
                        </td>
                        <td className="px-4 py-5 align-top text-right">
                          <div className="flex justify-end gap-2">
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                if (!canOpenReview) return;
                                navigate(`/ingestion/review/${rowTarget.id}`);
                              }}
                              className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-muted text-foreground transition hover:bg-muted/70"
                              aria-label={`Open submission ${rowTarget.id}`}
                              title="Open"
                              disabled={!canOpenReview}
                            >
                              <ArrowRight className="h-4 w-4" />
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
