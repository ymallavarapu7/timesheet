import React, { useState } from 'react';
import { AlertTriangle, ArrowRight, ChevronDown, ChevronRight, Clock, Loader2, Plus, RefreshCw, Search, Trash2, X } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import axios from 'axios';


import { Badge, Loading } from '@/components';
import { BulkSelectBar } from '@/components/ui/BulkSelectBar';
import { CreateClientFromDomainPopover } from '@/components/ui/CreateClientFromDomainPopover';
import {
  useAuth,
  useAssignChainCandidate,
  useBulkReprocessEmails,
  useBulkDeleteIngestedEmails,
  useClients,
  useCreateClient,
  useCreateClientFromDomain,
  useDeleteIngestedEmail,
  useFetchJobStatus,
  useIngestionTimesheets,
  useMailboxes,
  useReprocessIngestionEmail,
  useReprocessSkippedEmails,
  useSkippedEmails,
  useTriggerFetchEmails,
  useUpdateIngestionTimesheetData,
  useUsers,
} from '@/hooks';
import type { ChainCandidate, FetchMessageDiagnostic, IngestionTimesheetSummary, SkippedEmail } from '@/types';

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

// Rows older than this (in business days, weekends excluded) get an amber
// tint on the Received cell so reviewers can scan stale ones at a glance.
export const STALE_BUSINESS_DAYS = 5;

// Personal email providers — never auto-create a client from these domains.
// Mirror of the backend PERSONAL_EMAIL_DOMAINS set in ingestion_pipeline.py.
const PERSONAL_EMAIL_DOMAINS = new Set([
  'gmail.com',
  'outlook.com',
  'hotmail.com',
  'yahoo.com',
  'icloud.com',
  'aol.com',
  'live.com',
  'msn.com',
  'proton.me',
  'protonmail.com',
]);

export const domainOf = (email: string | null | undefined): string => {
  if (!email || !email.includes('@')) return '';
  return email.split('@', 2)[1].trim().toLowerCase();
};

export const isPersonalDomain = (domain: string): boolean =>
  PERSONAL_EMAIL_DOMAINS.has(domain.trim().toLowerCase());

// Smart-guess client name from a domain. "dxc.com" -> "DXC" (uppercase if
// short), "aegon.com" -> "Aegon" (title-case otherwise). Reviewer can edit.
export const suggestNameFromDomain = (domain: string): string => {
  const stem = (domain.split('.')[0] || domain).trim();
  if (!stem) return '';
  if (stem.length <= 4) return stem.toUpperCase();
  return stem.charAt(0).toUpperCase() + stem.slice(1).toLowerCase();
};

export const getInitials = (name: string | null | undefined, email?: string | null): string => {
  const source = (name || '').trim();
  if (source.includes(',')) {
    const [last, first] = source.split(',').map((part) => part.trim()).filter(Boolean);
    if (last && first) return (first.charAt(0) + last.charAt(0)).toUpperCase();
    if (last) return last.slice(0, 2).toUpperCase();
  }
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  // Fall back to the first two characters of the local-part of the email.
  const local = (email || '').split('@')[0] || '';
  if (local.length >= 2) return local.slice(0, 2).toUpperCase();
  return '?';
};

// Days between two dates, weekends excluded, rounded down. Returns 0 for
// today, fractional values are floored. Used to flag rows older than
// STALE_BUSINESS_DAYS.
const businessDaysBetween = (later: Date, earlier: Date): number => {
  const ms = later.getTime() - earlier.getTime();
  if (ms <= 0) return 0;
  const calendarDays = Math.floor(ms / (24 * 60 * 60 * 1000));
  // Cheap approximation: 5 business days per 7 calendar days. Good enough
  // for staleness highlighting; real business-day math would handle holidays.
  return Math.floor(calendarDays * (5 / 7));
};

export const formatRelativeReceived = (value: string | null | undefined): string => {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMinutes = Math.floor(diffMs / (60 * 1000));
  const diffHours = Math.floor(diffMs / (60 * 60 * 1000));
  const diffDays = Math.floor(diffMs / (24 * 60 * 60 * 1000));
  if (diffMinutes < 1) return 'Just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

export const isStaleReceived = (value: string | null | undefined): boolean => {
  if (!value) return false;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return false;
  return businessDaysBetween(new Date(), date) >= STALE_BUSINESS_DAYS;
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
  if (status === 'skipped') return 'outline';
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
  { key: 'skipped', label: 'Skipped' },
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
  kind?: 'timesheet' | 'skipped';
  skipped?: SkippedEmail;
};

// Adapt a SkippedEmail into the same row-group shape used by the main table,
// with status 'skipped' and placeholder fields for client/employee/week/hours.
const buildSkippedRowGroup = (email: SkippedEmail): TimesheetRowGroup => {
  const primary = {
    id: 0,
    email_id: email.id,
    sender_email: email.sender_email,
    sender_name: email.sender_name,
    subject: email.subject,
    received_at: email.received_at,
    created_at: email.received_at,
    mailbox_label: email.mailbox_label,
    client_name: null,
    employee_name: null,
    extracted_employee_name: null,
    employee_id: null,
    client_id: null,
    period_start: null,
    period_end: null,
    total_hours: null,
    status: 'skipped',
    attachment_id: email.reprocessable_attachments[0]?.id ?? null,
    llm_anomalies: [],
    is_likely_resubmission: false,
  } as unknown as IngestionTimesheetSummary;
  return {
    key: `skipped-${email.id}`,
    status: 'skipped',
    timesheets: [primary],
    primary,
    periods: 1,
    totalHours: 0,
    anomalyCount: 0,
    kind: 'skipped',
    skipped: email,
  };
};

const buildRowGroups = (timesheets: IngestionTimesheetSummary[]): TimesheetRowGroup[] => {
  const map = new Map<string, TimesheetRowGroup>();

  for (const ts of timesheets) {
    // Group all timesheets from the same email into one inbox row.
    // The review panel shows individual week tabs inside.
    const key = `email-${ts.email_id}`;
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

  // Cascade-create-client-from-domain popover state.
  const [cascadePopover, setCascadePopover] = React.useState<{
    domain: string;
    anchorEl: HTMLElement;
  } | null>(null);
  const createClientFromDomain = useCreateClientFromDomain();

  const assignChainCandidate = useAssignChainCandidate();
  const updateTimesheet = useUpdateIngestionTimesheetData();
  const createClient = useCreateClient();
  const { data: users = [] } = useUsers();
  // Which row has an inline picker open: { id, kind: 'client'|'employee' }
  const [inlinePicker, setInlinePicker] = React.useState<{ id: number; kind: 'client' | 'employee' } | null>(null);
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
  const [deletingEmailId, setDeletingEmailId] = useState<number | null>(null);
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

  // Pre-fill with an existing-client fuzzy match, else the smart-guess.
  const cascadeInitialValue = React.useMemo(() => {
    if (!cascadePopover) return '';
    const guess = suggestNameFromDomain(cascadePopover.domain);
    const guessLower = guess.toLowerCase();
    if (!guessLower) return guess;
    const list = clients as Array<{ id: number; name: string }>;
    const fuzzy = list.find((c) => {
      const name = (c.name || '').toLowerCase();
      return (
        name === guessLower
        || name.startsWith(guessLower + ' ')
        || name.endsWith(' ' + guessLower)
        || name.includes(' ' + guessLower + ' ')
      );
    });
    return fuzzy ? fuzzy.name : guess;
  }, [cascadePopover, clients]);
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
  const actionableSkippedEmails = React.useMemo(() => {
    const rows = skippedOverview?.emails ?? [];
    return rows.filter(isActionableSkippedEmail);
  }, [skippedOverview]);
  const skippedGroups = React.useMemo(
    () => actionableSkippedEmails.map(buildSkippedRowGroup),
    [actionableSkippedEmails],
  );
  const allGroups = React.useMemo(
    () => [...buildRowGroups(allTimesheets), ...skippedGroups],
    [allTimesheets, skippedGroups],
  );
  const groups = React.useMemo(() => {
    const baseGroups = buildRowGroups(timesheets);
    // Skipped rows aren't filtered server-side, so mirror the client-side
    // status/search/client filters here to keep the table consistent.
    const searchLower = search.trim().toLowerCase();
    const skippedVisible = skippedGroups.filter((group) => {
      if (statusFilter && statusFilter !== 'skipped') return false;
      if (clientId) return false; // skipped emails have no client
      if (!searchLower) return true;
      const email = group.skipped;
      return (
        (email?.subject ?? '').toLowerCase().includes(searchLower) ||
        (email?.sender_email ?? '').toLowerCase().includes(searchLower) ||
        (email?.sender_name ?? '').toLowerCase().includes(searchLower)
      );
    });
    // When the 'skipped' tab is active, only show skipped rows.
    if (statusFilter === 'skipped') return skippedVisible;
    return [...baseGroups, ...skippedVisible];
  }, [timesheets, skippedGroups, statusFilter, clientId, search]);
  const statusCounts = React.useMemo(() => countStatuses(allGroups), [allGroups]);
  const skippedCount = statusCounts.skipped ?? 0;

  // Persist the dismissed-at count per tenant so the banner stays dismissed
  // across refreshes, but reappears once more emails land in the skipped pile
  // than the user last acknowledged. We only read/write localStorage on the
  // client, and we guard against SSR / disabled storage.
  const tenantScopeKey = user?.tenant_id != null ? `inbox.skippedBannerDismissedCount.${user.tenant_id}` : null;
  const [dismissedSkippedCount, setDismissedSkippedCount] = React.useState<number>(() => {
    if (typeof window === 'undefined' || !tenantScopeKey) return 0;
    try {
      const raw = window.localStorage.getItem(tenantScopeKey);
      const parsed = raw == null ? 0 : Number.parseInt(raw, 10);
      return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
    } catch {
      return 0;
    }
  });
  const dismissSkippedBanner = React.useCallback(() => {
    setDismissedSkippedCount(skippedCount);
    if (typeof window !== 'undefined' && tenantScopeKey) {
      try {
        window.localStorage.setItem(tenantScopeKey, String(skippedCount));
      } catch {
        // Storage quota / private-mode — banner will simply re-show next load.
      }
    }
  }, [skippedCount, tenantScopeKey]);
  const showSkippedBanner =
    skippedCount > 0 &&
    skippedCount > dismissedSkippedCount &&
    statusFilter !== 'skipped';

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

  // Pending count for a given domain across the currently visible groups.
  // Personal-domain groups are excluded since they don't participate in the
  // cascade (the backend rejects gmail/outlook/etc. with 422).
  const cascadePendingCount = (domain: string): number => {
    const target = domain.trim().toLowerCase();
    if (!target) return 0;
    return groups.reduce((accumulator, group) => {
      if (group.kind === 'skipped') return accumulator;
      if (group.primary.client_id != null) return accumulator;
      if (domainOf(group.primary.sender_email) !== target) return accumulator;
      return accumulator + 1;
    }, 0);
  };

  const handleCascadeConfirm = async (
    domain: string,
    payload: { name: string; existing: { id: number; name: string } | null },
  ) => {
    try {
      const result = await createClientFromDomain.mutateAsync({
        name: payload.existing ? payload.existing.name : payload.name,
        domain,
      });
      setCascadePopover(null);
      setStatusTone('success');
      setStatusMessage(
        result.cascaded_count > 0
          ? `Assigned ${result.client.name} to ${result.cascaded_count} pending email${result.cascaded_count === 1 ? '' : 's'} from ${domain}.`
          : `Created ${result.client.name} from ${domain}.`,
      );
    } catch (error) {
      // 409 conflict: the domain is already mapped to another client. Surface
      // the existing-client info to the reviewer so they can decide.
      if (axios.isAxiosError(error) && error.response?.status === 409) {
        const detail = error.response.data?.detail as
          | { message?: string; existing_client_name?: string }
          | undefined;
        setStatusTone('danger');
        setStatusMessage(
          detail?.message
            || (detail?.existing_client_name
              ? `Domain '${domain}' is already mapped to '${detail.existing_client_name}'.`
              : `Domain '${domain}' is already mapped to another client.`),
        );
        return;
      }
      setStatusTone('danger');
      setStatusMessage(getApiErrorMessage(error, 'Unable to assign client from domain.'));
    }
  };

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
    setDeletingEmailId(emailId);
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
    } finally {
      setDeletingEmailId(null);
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

      {showSkippedBanner ? (
        <div
          role="status"
          aria-live="polite"
          data-testid="skipped-emails-banner"
          className="surface-card flex flex-wrap items-center justify-between gap-3 border-amber-300/30 bg-amber-500/5 px-5 py-3"
        >
          <div className="text-sm text-foreground">
            <span className="font-medium">{skippedCount}</span>{' '}
            {skippedCount === 1 ? 'email was' : 'emails were'} skipped during ingestion.{' '}
            <button
              type="button"
              className="font-medium text-primary underline-offset-4 hover:underline"
              onClick={() => setStatusFilter('skipped')}
            >
              View skipped
            </button>{' '}
            to reprocess individually, or reprocess them all now.
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleReprocessSkipped()}
              disabled={isBusy}
              className="action-button-secondary disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Reprocess {skippedCount} skipped
            </button>
            <button
              type="button"
              onClick={dismissSkippedBanner}
              aria-label="Dismiss skipped emails banner"
              className="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
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
            <div className="flex flex-wrap items-center gap-2">
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
              {statusFilter === 'skipped' && skippedCount > 0 ? (
                <button
                  type="button"
                  onClick={() => void handleReprocessSkipped()}
                  disabled={isBusy}
                  data-testid="reprocess-all-skipped"
                  className="ml-auto action-button-secondary disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Reprocess {skippedCount} skipped
                </button>
              ) : null}
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
                <tr className="text-xs uppercase tracking-[0.06em] text-muted-foreground">
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
                  <th className="px-4 py-4 font-medium">Status</th>
                  <th className="px-4 py-4 font-medium">Client</th>
                  <th className="px-4 py-4 font-medium">Employee</th>
                  <th className="px-4 py-4 font-medium">Week</th>
                  <th className="px-4 py-4 font-medium">Hours</th>
                  <th className="px-4 py-4 font-medium">Received</th>
                  <th className="px-4 py-4 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => {
                  const isSkipped = group.kind === 'skipped';
                  const isMultiPeriod = group.periods > 1;
                  const rowTarget = group.primary;
                  const canOpenReview = isSkipped
                    ? Boolean(group.skipped?.id)
                    : Number.isInteger(rowTarget.id) && rowTarget.id > 0;
                  const openReview = () => {
                    if (isSkipped && group.skipped) {
                      navigate(`/ingestion/email/${group.skipped.id}`);
                    } else if (canOpenReview) {
                      navigate(`/ingestion/review/${rowTarget.id}`);
                    }
                  };

                  return (
                    <React.Fragment key={group.key}>
                      <tr
                        className={`group h-11 transition hover:bg-muted ${canOpenReview ? 'cursor-pointer' : 'cursor-default'}`}
                        onClick={() => openReview()}
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
                          <div className="group/sender flex min-w-[180px] items-start gap-3">
                            <div
                              className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold uppercase tracking-wide text-slate-100 ring-1 ring-inset ring-white/5 dark:ring-white/10"
                              style={{ background: 'linear-gradient(135deg, #334155, #1e293b)' }}
                              aria-hidden="true"
                            >
                              {getInitials(rowTarget.sender_name, rowTarget.sender_email)}
                            </div>
                            <div className="min-w-0">
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
                              <p
                                className="mt-1 max-h-0 overflow-hidden font-mono text-xs text-muted-foreground opacity-0 transition-all duration-150 group-hover:max-h-6 group-hover:opacity-100 group-focus-within:max-h-6 group-focus-within:opacity-100"
                              >
                                {rowTarget.sender_email || '--'}
                              </p>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-5 align-top">
                          <div className="min-w-[200px] space-y-2">
                            <p className="font-medium text-foreground" title={rowTarget.subject ?? undefined}>{rowTarget.subject || 'No subject'}</p>
                            {isMultiPeriod ? (
                              <span className="inline-flex items-center rounded-full border border-blue-400/40 bg-blue-500/10 px-2.5 py-0.5 text-xs font-medium text-blue-700 dark:text-blue-300">
                                {group.periods} weeks
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td className="px-4 py-5 align-top whitespace-nowrap">
                          <Badge tone={getStatusTone(group.status)} className="normal-case tracking-normal whitespace-nowrap">
                            {statusLabel(group.status)}
                          </Badge>
                        </td>
                        <td className="px-4 py-5 align-top text-sm">
                          {rowTarget.client_name ? (
                            <span className="text-sm text-foreground">{rowTarget.client_name}</span>
                          ) : isSkipped ? (
                            <span className="text-sm text-muted-foreground">--</span>
                          ) : (() => {
                            const senderDomain = domainOf(rowTarget.sender_email);
                            if (!senderDomain || isPersonalDomain(senderDomain)) {
                              const pickerId = rowTarget.id;
                              const isOpen = inlinePicker?.id === pickerId && inlinePicker.kind === 'client';
                              return isOpen ? (
                                <div className="flex flex-col gap-1 min-w-[160px]" onClick={(e) => e.stopPropagation()}>
                                  <select
                                    autoFocus
                                    className="h-7 rounded border border-border bg-background px-2 text-xs"
                                    defaultValue=""
                                    onChange={async (e) => {
                                      const val = e.target.value;
                                      if (!val) return;
                                      await updateTimesheet.mutateAsync({ id: pickerId, data: { client_id: Number(val) } });
                                      setInlinePicker(null);
                                    }}
                                    onBlur={() => setInlinePicker(null)}
                                  >
                                    <option value="">Pick client…</option>
                                    {clients.map((c: { id: number; name: string }) => (
                                      <option key={c.id} value={c.id}>{c.name}</option>
                                    ))}
                                  </select>
                                  {rowTarget.extracted_client_name && (
                                    <button
                                      type="button"
                                      className="text-left text-xs text-primary hover:underline disabled:opacity-60"
                                      disabled={createClient.isPending}
                                      onMouseDown={async (e) => {
                                        e.preventDefault();
                                        const created = await createClient.mutateAsync({ name: rowTarget.extracted_client_name! });
                                        await updateTimesheet.mutateAsync({ id: pickerId, data: { client_id: created.id } });
                                        setInlinePicker(null);
                                      }}
                                    >
                                      {createClient.isPending ? 'Creating…' : `+ Create "${rowTarget.extracted_client_name}"`}
                                    </button>
                                  )}
                                </div>
                              ) : (
                                <button
                                  type="button"
                                  onClick={(e) => { e.stopPropagation(); setInlinePicker({ id: pickerId, kind: 'client' }); }}
                                  className="inline-flex items-center rounded-full border border-amber-400/40 bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-700 transition hover:bg-amber-500/20 dark:text-amber-300"
                                  title="Click to assign client"
                                >
                                  Needs client
                                </button>
                              );
                            }
                            const count = cascadePendingCount(senderDomain);
                            return (
                              <button
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setCascadePopover({
                                    domain: senderDomain,
                                    anchorEl: event.currentTarget,
                                  });
                                }}
                                className="inline-flex items-center gap-1 rounded-full border border-amber-400/40 bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-700 transition hover:bg-amber-500/20 dark:text-amber-300"
                                title={`Create or link a client for ${senderDomain}`}
                              >
                                <Plus className="h-3.5 w-3.5" />
                                {senderDomain}
                                {count > 1 ? <span className="opacity-60">({count})</span> : null}
                              </button>
                            );
                          })()}
                        </td>
                        <td className="px-4 py-5 align-top">
                          {rowTarget.employee_name || rowTarget.extracted_employee_name ? (
                            <span className="text-sm text-foreground">
                              {cleanEmployeeNameForDisplay(rowTarget.employee_name || rowTarget.extracted_employee_name)}
                            </span>
                          ) : isSkipped ? (
                            <span className="text-sm text-muted-foreground">--</span>
                          ) : (() => {
                            const candidates: ChainCandidate[] = rowTarget.llm_match_suggestions?.chain_candidates ?? [];
                            if (candidates.length > 0) {
                              return (
                                <div className="flex flex-wrap gap-1">
                                  {candidates.map((c, i) => (
                                    <button
                                      key={i}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        assignChainCandidate.mutate({ id: rowTarget.id, data: { name: c.name, email: c.email } });
                                      }}
                                      className="inline-flex items-center rounded-full border border-blue-400/40 bg-blue-500/10 px-2.5 py-0.5 text-xs font-medium text-blue-700 dark:text-blue-300 hover:bg-blue-500/20 transition-colors"
                                      title={c.email ?? undefined}
                                    >
                                      {c.name || c.email}
                                    </button>
                                  ))}
                                </div>
                              );
                            }
                            const pickerId = rowTarget.id;
                            const isOpen = inlinePicker?.id === pickerId && inlinePicker.kind === 'employee';
                            return isOpen ? (
                              <div onClick={(e) => e.stopPropagation()}>
                                <select
                                  autoFocus
                                  className="h-7 rounded border border-border bg-background px-2 text-xs min-w-[160px]"
                                  defaultValue=""
                                  onChange={async (e) => {
                                    const val = e.target.value;
                                    if (!val) return;
                                    await updateTimesheet.mutateAsync({ id: pickerId, data: { employee_id: Number(val) } });
                                    setInlinePicker(null);
                                  }}
                                  onBlur={() => setInlinePicker(null)}
                                >
                                  <option value="">Pick employee…</option>
                                  {users.map((u: { id: number; full_name: string }) => (
                                    <option key={u.id} value={u.id}>{u.full_name}</option>
                                  ))}
                                </select>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); setInlinePicker({ id: pickerId, kind: 'employee' }); }}
                                className="inline-flex items-center rounded-full border border-amber-400/40 bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-700 transition hover:bg-amber-500/20 dark:text-amber-300"
                                title="Click to assign employee"
                              >
                                Needs employee
                              </button>
                            );
                          })()}
                        </td>
                        <td className="px-4 py-5 align-top text-sm text-muted-foreground whitespace-nowrap">
                          {isMultiPeriod
                            ? formatDateRange(group.timesheets[0]?.period_start ?? null, group.timesheets[group.timesheets.length - 1]?.period_end ?? null)
                            : formatDateRange(rowTarget.period_start, rowTarget.period_end)}
                        </td>
                        <td className="px-4 py-5 align-top">
                          {isSkipped ? (
                            <span className="text-sm text-muted-foreground">--</span>
                          ) : group.anomalyCount > 0 ? (
                            <span
                              className="inline-flex items-center gap-1 whitespace-nowrap font-mono text-sm font-medium text-amber-700 dark:text-amber-400"
                              title={`${group.anomalyCount} anomaly${group.anomalyCount === 1 ? '' : 'ies'} flagged. Open to review.`}
                            >
                              {formatHours(group.totalHours)}
                              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                            </span>
                          ) : (
                            <span className="whitespace-nowrap font-mono text-sm font-medium text-foreground">{formatHours(group.totalHours)}</span>
                          )}
                        </td>
                        <td className="px-4 py-5 align-top">
                          {(() => {
                            const ts = rowTarget.received_at || rowTarget.created_at;
                            const stale = !isSkipped && isStaleReceived(ts);
                            const label = formatRelativeReceived(ts);
                            const date = ts ? new Date(ts) : null;
                            const titleAttr = date && !Number.isNaN(date.getTime())
                              ? date.toLocaleString()
                              : undefined;
                            return (
                              <span
                                className={stale ? 'inline-flex items-center gap-1 text-sm font-medium text-amber-700 dark:text-amber-400 whitespace-nowrap' : 'text-sm text-muted-foreground whitespace-nowrap'}
                                title={stale ? `Waiting longer than ${STALE_BUSINESS_DAYS} business days${titleAttr ? ' · ' + titleAttr : ''}` : titleAttr}
                              >
                                {stale && <Clock className="h-3.5 w-3.5 shrink-0" />}
                                {label}
                              </span>
                            );
                          })()}
                        </td>
                        <td className="px-4 py-5 align-top text-right">
                          <div className="flex justify-end gap-2">
                            {isSkipped && group.skipped ? (
                              <button
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void handleReprocessEmail(group.skipped!.id);
                                }}
                                className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-muted text-foreground transition hover:bg-muted/70"
                                aria-label={`Reprocess email ${group.skipped.id}`}
                                title="Reprocess"
                                disabled={isBusy}
                              >
                                <RefreshCw className="h-4 w-4" />
                              </button>
                            ) : null}
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                openReview();
                              }}
                              className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-muted text-foreground transition hover:bg-muted/70"
                              aria-label={isSkipped ? `Open email ${group.skipped?.id}` : `Open submission ${rowTarget.id}`}
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
                              disabled={isBusy}
                              className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-muted text-foreground transition hover:bg-destructive/10 hover:text-destructive disabled:opacity-40"
                              aria-label={`Delete email ${rowTarget.email_id}`}
                              title="Delete"
                            >
                              {deletingEmailId === rowTarget.email_id
                                ? <Loader2 className="h-4 w-4 animate-spin" />
                                : <Trash2 className="h-4 w-4" />
                              }
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

      <CreateClientFromDomainPopover
        open={cascadePopover != null}
        domain={cascadePopover?.domain ?? ''}
        anchorEl={cascadePopover?.anchorEl ?? null}
        cascadeCount={cascadePopover ? cascadePendingCount(cascadePopover.domain) : 0}
        existingClients={clients as Array<{ id: number; name: string }>}
        initialValue={cascadeInitialValue}
        isSubmitting={createClientFromDomain.isPending}
        onConfirm={(payload) => {
          if (cascadePopover) void handleCascadeConfirm(cascadePopover.domain, payload);
        }}
        onClose={() => setCascadePopover(null)}
      />
    </div>
  );
};
