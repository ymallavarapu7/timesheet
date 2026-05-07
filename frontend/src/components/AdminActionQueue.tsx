import React from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, AlertTriangle, ArrowRight, Bell, CheckCircle2, Clock, FileWarning, MailQuestion, UserPlus, X } from 'lucide-react';

import { useDismissAttentionSignal, useDismissedAttentionSignals } from '@/hooks';
import type { DashboardRecentActivityItem, NotificationItem, User } from '@/types';

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
  users: User[];
  notifications: NotificationItem[];
  recentActivity: DashboardRecentActivityItem[];
  recentActivityLoading: boolean;
  currentUserId: number | null;
  onOpenNotifications: () => void;
}

const RECENT_ERROR_LOOKBACK_HOURS = 24;
const STALE_INVITATION_DAYS = 7;
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

const SNOOZE_OPTIONS: Array<{ label: string; ms: number | null }> = [
  { label: 'Dismiss', ms: null },
  { label: 'Remind me in 1 hour', ms: 60 * 60 * 1000 },
  { label: 'Remind me tomorrow', ms: 24 * 60 * 60 * 1000 },
  { label: 'Remind me next week', ms: 7 * 24 * 60 * 60 * 1000 },
];

const DismissMenu: React.FC<{
  onPick: (snoozedUntil: string | null) => void;
  onClose: () => void;
}> = ({ onPick, onClose }) => {
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [onClose]);
  return (
    <div
      ref={ref}
      className="absolute right-0 top-7 z-20 w-48 rounded-md border border-border bg-popover shadow-lg p-1"
      role="menu"
    >
      {SNOOZE_OPTIONS.map(({ label, ms }) => (
        <button
          key={label}
          type="button"
          className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-foreground hover:bg-muted"
          onClick={(e) => {
            e.stopPropagation();
            const snoozedUntil = ms === null ? null : new Date(Date.now() + ms).toISOString();
            onPick(snoozedUntil);
            onClose();
          }}
        >
          {ms === null ? <X className="h-3.5 w-3.5" /> : <Clock className="h-3.5 w-3.5" />}
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
};

export const AdminActionQueue: React.FC<AdminActionQueueProps> = ({
  users,
  notifications,
  recentActivity,
  recentActivityLoading,
  currentUserId,
  onOpenNotifications,
}) => {
  const navigate = useNavigate();
  const { data: dismissed = [] } = useDismissedAttentionSignals();
  const dismissMutation = useDismissAttentionSignal();
  const [openMenuFor, setOpenMenuFor] = React.useState<string | null>(null);

  const dismissedKeys = React.useMemo(
    () => new Set(dismissed.map((d) => d.signal_key)),
    [dismissed],
  );

  const items: ActionItem[] = [];

  // Internal users only — external users (ingestion-only records) never
  // log in or get approved, so the "approval chain is broken" framing
  // doesn't apply.
  const orphanRoles = new Set(['EMPLOYEE', 'MANAGER']);
  const usersWithoutManager = users.filter(
    (u) => u.is_active && !u.is_external && orphanRoles.has(u.role) && (u.manager_id == null),
  );
  if (usersWithoutManager.length > 0) {
    const sample = usersWithoutManager.slice(0, 3).map((u) => u.full_name).join(', ');
    items.push({
      id: 'no-manager',
      urgency: 'urgent',
      icon: UserPlus,
      title: `${usersWithoutManager.length} user${usersWithoutManager.length === 1 ? '' : 's'} without a manager`,
      detail: sample
        ? `${sample}${usersWithoutManager.length > 3 ? ` and ${usersWithoutManager.length - 3} more` : ''}. Approval chain is broken until assigned.`
        : 'Approval chain is broken until assigned.',
      cta: 'Assign managers',
      onClick: () => navigate('/user-management?status=NO_MANAGER'),
    });
  }

  const staleCutoff = Date.now() - STALE_INVITATION_DAYS * 24 * 60 * 60 * 1000;
  const staleInvites = users.filter((u) => {
    if (!u.is_active) return false;
    if (u.email_verified) return false;
    if (u.is_external) return false;
    const created = u.created_at ? Date.parse(u.created_at) : NaN;
    return Number.isFinite(created) && created < staleCutoff;
  });
  if (staleInvites.length > 0) {
    items.push({
      id: 'stale-invitations',
      urgency: 'warn',
      icon: MailQuestion,
      title: `${staleInvites.length} unverified invitation${staleInvites.length === 1 ? '' : 's'} > ${STALE_INVITATION_DAYS}d old`,
      detail: 'Resend or revoke. Unverified accounts can\'t log in.',
      cta: 'Open users',
      onClick: () => navigate('/user-management?verified=NO'),
    });
  }

  const recentErrorCutoff = Date.now() - RECENT_ERROR_LOOKBACK_HOURS * 60 * 60 * 1000;
  const recentErrors = recentActivity.filter((item) => {
    if (item.severity !== 'error') return false;
    if (currentUserId != null && item.actor_id === currentUserId) return false;
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

  const recentWarnings = recentActivity.filter((item) => {
    if (item.severity !== 'warning') return false;
    if (currentUserId != null && item.actor_id === currentUserId) return false;
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

  const filtered = items.filter((it) => !dismissedKeys.has(it.id));
  filtered.sort((a, b) => urgencyOrder[a.urgency] - urgencyOrder[b.urgency]);

  const visible = filtered.slice(0, MAX_VISIBLE);
  const hidden = filtered.length - visible.length;

  const handleDismiss = (signalKey: string, snoozedUntil: string | null) => {
    dismissMutation.mutate({ signal_key: signalKey, snoozed_until: snoozedUntil });
  };

  if (recentActivityLoading && filtered.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
        <p className="text-sm text-muted-foreground">Loading attention queue...</p>
      </div>
    );
  }

  if (filtered.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground">All caught up</p>
            <p className="text-xs text-muted-foreground">
              No org-chart gaps, no stale invitations, no recent errors, no unread notifications.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="surface-card p-5 mb-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-base font-semibold text-foreground">Needs your attention</h2>
        <span className="text-xs text-muted-foreground">
          {filtered.length} {filtered.length === 1 ? 'item' : 'items'}
        </span>
      </div>
      <ul className="space-y-2">
        {visible.map((item) => {
          const Icon = item.icon;
          return (
            <li key={item.id} className="relative">
              <button
                type="button"
                onClick={item.onClick}
                className="group flex w-full items-center gap-3 rounded-lg border border-border/60 bg-background/40 px-3 py-2.5 pr-8 text-left transition hover:border-primary/40 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
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
              <button
                type="button"
                aria-label="Dismiss or snooze"
                title="Dismiss or snooze"
                onClick={(e) => {
                  e.stopPropagation();
                  setOpenMenuFor((prev) => (prev === item.id ? null : item.id));
                }}
                className="absolute -top-1.5 -right-1.5 z-10 flex h-5 w-5 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-sm hover:bg-muted hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
              {openMenuFor === item.id && (
                <DismissMenu
                  onPick={(snoozedUntil) => handleDismiss(item.id, snoozedUntil)}
                  onClose={() => setOpenMenuFor(null)}
                />
              )}
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
