import React from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, AlertTriangle, ArrowRight, Bell, CheckCircle2, FileWarning, Inbox, UserSquare } from 'lucide-react';

import type { DashboardRecentActivityItem, IngestionTimesheetSummary, NotificationItem } from '@/types';

type Urgency = 'urgent' | 'warn' | 'info';

interface ActionItem {
  id: string;
  urgency: Urgency;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  detail: string;
  cta: string;
  onClick: () => void;
}

interface AdminActionQueueProps {
  /** Full pending list. We derive count + per-domain breakdown from this. */
  pendingTimesheets: IngestionTimesheetSummary[];
  ingestionEnabled: boolean;
  canReview: boolean;
  notifications: NotificationItem[];
  recentActivity: DashboardRecentActivityItem[];
  recentActivityLoading: boolean;
  onOpenNotifications: () => void;
}

const domainOf = (email: string | null | undefined): string | null => {
  if (!email) return null;
  const at = email.lastIndexOf('@');
  if (at < 0) return null;
  const dom = email.slice(at + 1).trim().toLowerCase();
  return dom || null;
};

const PERSONAL_DOMAINS = new Set([
  'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'live.com',
  'yahoo.com', 'icloud.com', 'me.com', 'aol.com', 'proton.me', 'protonmail.com',
]);

const formatRelativeAge = (iso: string | null | undefined): string => {
  if (!iso) return '';
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return '';
  const diffMs = Date.now() - ts;
  if (diffMs < 60_000) return 'just now';
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
};

const PENDING_REVIEW_WARN_THRESHOLD = 5;
const PENDING_REVIEW_URGENT_THRESHOLD = 15;
const RECENT_ERROR_LOOKBACK_HOURS = 24;
const MAX_VISIBLE = 5;

const urgencyDot: Record<Urgency, string> = {
  urgent: 'bg-red-500',
  warn: 'bg-amber-500',
  info: 'bg-sky-500',
};

const urgencyChip: Record<Urgency, string> = {
  urgent: 'border-red-400/40 bg-red-500/10 text-red-700 dark:text-red-300',
  warn: 'border-amber-400/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  info: 'border-sky-400/40 bg-sky-500/10 text-sky-700 dark:text-sky-300',
};

const urgencyOrder: Record<Urgency, number> = { urgent: 0, warn: 1, info: 2 };

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

export const AdminActionQueue: React.FC<AdminActionQueueProps> = ({
  pendingTimesheets,
  ingestionEnabled,
  canReview,
  notifications,
  recentActivity,
  recentActivityLoading,
  onOpenNotifications,
}) => {
  const navigate = useNavigate();

  const pendingReviewCount = pendingTimesheets.length;
  const items: ActionItem[] = [];

  // Pending ingestion reviews. Urgency tiers based on backlog size:
  // small backlog is just informational, growing backlog warns, large
  // backlog is urgent (reviewers can fall behind quickly when emails
  // pile up over a weekend).
  if (canReview && ingestionEnabled && pendingReviewCount > 0) {
    const urgency: Urgency =
      pendingReviewCount >= PENDING_REVIEW_URGENT_THRESHOLD ? 'urgent'
      : pendingReviewCount >= PENDING_REVIEW_WARN_THRESHOLD ? 'warn'
      : 'info';
    // Detail line shows oldest age so the reviewer knows whether the
    // backlog is fresh or stale. Sort by created_at ascending and read
    // the first row.
    const sortedByOldest = [...pendingTimesheets].sort((a, b) => {
      const aTs = Date.parse(a.created_at);
      const bTs = Date.parse(b.created_at);
      return (Number.isFinite(aTs) ? aTs : 0) - (Number.isFinite(bTs) ? bTs : 0);
    });
    const oldestAge = formatRelativeAge(sortedByOldest[0]?.created_at);
    items.push({
      id: 'pending-reviews',
      urgency,
      icon: Inbox,
      title: `${pendingReviewCount} timesheet${pendingReviewCount === 1 ? '' : 's'} awaiting review`,
      detail: oldestAge
        ? `Email ingestion has staged submissions. Oldest ${oldestAge}.`
        : 'Email ingestion has staged submissions that need reviewer action.',
      cta: 'Open inbox',
      onClick: () => navigate('/ingestion/inbox'),
    });
  }

  // Pending client assignment: rows where ingestion has not yet
  // resolved a client. We bucket by sender domain (skipping personal
  // domains) so the reviewer sees the cascade target. A single click
  // through the inbox cascade button on each domain resolves all of
  // them at once.
  if (canReview && ingestionEnabled && pendingTimesheets.length > 0) {
    const domainCounts = new Map<string, number>();
    let totalUnassigned = 0;
    for (const t of pendingTimesheets) {
      if (t.client_id != null) continue;
      totalUnassigned += 1;
      const dom = domainOf(t.sender_email);
      if (!dom || PERSONAL_DOMAINS.has(dom)) continue;
      domainCounts.set(dom, (domainCounts.get(dom) ?? 0) + 1);
    }
    if (totalUnassigned > 0 && domainCounts.size > 0) {
      const top = [...domainCounts.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([d, n]) => `${n} from ${d}`)
        .join(' · ');
      items.push({
        id: 'unassigned-clients',
        urgency: 'warn',
        icon: UserSquare,
        title: `${totalUnassigned} email${totalUnassigned === 1 ? '' : 's'} awaiting client assignment`,
        detail: top || 'Sender domain not yet mapped to a client.',
        cta: 'Resolve',
        onClick: () => navigate('/ingestion/inbox'),
      });
    }
  }

  // Error-severity activity from the last 24 hours. These are the
  // signals an admin most likely wants to act on first; lower-severity
  // activity stays in the Recent Activity card below.
  const recentErrorCutoff = Date.now() - RECENT_ERROR_LOOKBACK_HOURS * 60 * 60 * 1000;
  const recentErrors = recentActivity.filter((item) => {
    if (item.severity !== 'error') return false;
    const ts = Date.parse(item.created_at);
    return Number.isFinite(ts) && ts >= recentErrorCutoff;
  });
  recentErrors.slice(0, 3).forEach((item) => {
    items.push({
      id: `activity-${item.id}`,
      urgency: 'urgent',
      icon: AlertCircle,
      title: item.summary,
      detail: 'Recent error in the org. Investigate before it cascades.',
      cta: 'Investigate',
      onClick: () => navigate(buildRouteWithParams(item.route, item.route_params)),
    });
  });

  // Warning-severity activity (also last 24h). One row per warning,
  // capped so a noisy day doesn't flood the queue.
  const recentWarnings = recentActivity.filter((item) => {
    if (item.severity !== 'warning') return false;
    const ts = Date.parse(item.created_at);
    return Number.isFinite(ts) && ts >= recentErrorCutoff;
  });
  recentWarnings.slice(0, 2).forEach((item) => {
    items.push({
      id: `activity-${item.id}`,
      urgency: 'warn',
      icon: AlertTriangle,
      title: item.summary,
      detail: 'Recent warning in the org. Worth a look.',
      cta: 'Review',
      onClick: () => navigate(buildRouteWithParams(item.route, item.route_params)),
    });
  });

  // Unread notifications, grouped (the notifications endpoint already
  // collapses by route + count). Surface anything with count > 0 as
  // info; the notifications modal shows the full list.
  const unreadNotifications = notifications.filter((n) => !n.is_read && n.count > 0);
  if (unreadNotifications.length > 0) {
    const total = unreadNotifications.reduce((sum, n) => sum + n.count, 0);
    items.push({
      id: 'notifications',
      urgency: unreadNotifications.some((n) => n.severity === 'error') ? 'urgent'
        : unreadNotifications.some((n) => n.severity === 'warning') ? 'warn'
        : 'info',
      icon: Bell,
      title: `${total} unread notification${total === 1 ? '' : 's'}`,
      detail: unreadNotifications[0]?.title ?? 'Open the notifications panel for details.',
      cta: 'View',
      onClick: onOpenNotifications,
    });
  }

  // Sort by urgency, preserving insertion order within a tier.
  items.sort((a, b) => urgencyOrder[a.urgency] - urgencyOrder[b.urgency]);

  const visible = items.slice(0, MAX_VISIBLE);
  const hidden = items.length - visible.length;

  if (recentActivityLoading && items.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-5 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
        <p className="text-sm text-muted-foreground">Loading action queue...</p>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-5 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground">All caught up</p>
            <p className="text-xs text-muted-foreground">
              No pending reviews, no recent errors, no unread notifications.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-5 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">Admin priorities</h2>
        <span className="text-xs text-muted-foreground">
          {items.length} {items.length === 1 ? 'item' : 'items'}
        </span>
      </div>
      <ul className="space-y-2">
        {visible.map((item) => {
          const Icon = item.icon;
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={item.onClick}
                className="group flex w-full items-center gap-3 rounded-md border border-border/60 bg-background/40 px-3 py-3 text-left transition hover:border-primary/40 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
              >
                <span
                  aria-hidden
                  className={`inline-block h-2 w-2 shrink-0 rounded-full ${urgencyDot[item.urgency]}`}
                />
                <span className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border ${urgencyChip[item.urgency]}`}>
                  <Icon className="h-4 w-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-foreground">{item.title}</span>
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">{item.detail}</span>
                </span>
                <span className="ml-2 hidden shrink-0 items-center gap-1 text-xs font-medium text-primary group-hover:flex">
                  {item.cta}
                  <ArrowRight className="h-3.5 w-3.5" />
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {hidden > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">
          <FileWarning className="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
          {hidden} more {hidden === 1 ? 'item' : 'items'} not shown. Resolve top items to clear the queue.
        </p>
      )}
    </div>
  );
};
