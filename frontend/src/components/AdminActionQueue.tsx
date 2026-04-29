import React from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, AlertTriangle, ArrowRight, Bell, CheckCircle2, FileWarning, MailQuestion, UserPlus } from 'lucide-react';

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
  /** Tenant users. Used to surface users-without-manager and stale
      unverified invitations. The dashboard already loads this list for
      its glance tiles, so this is a free re-use. */
  users: User[];
  notifications: NotificationItem[];
  recentActivity: DashboardRecentActivityItem[];
  recentActivityLoading: boolean;
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

export const AdminActionQueue: React.FC<AdminActionQueueProps> = ({
  users,
  notifications,
  recentActivity,
  recentActivityLoading,
  onOpenNotifications,
}) => {
  const navigate = useNavigate();
  const items: ActionItem[] = [];

  // Active employees and managers without a direct manager assigned.
  // ADMIN, PLATFORM_ADMIN, and CEO legitimately may not have one;
  // anyone else lacking a manager_id is an org-chart gap that breaks
  // the approval chain.
  const orphanRoles = new Set(['EMPLOYEE', 'MANAGER', 'SENIOR_MANAGER']);
  const usersWithoutManager = users.filter(
    (u) => u.is_active && orphanRoles.has(u.role) && (u.manager_id == null),
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

  // Stale invitations: active accounts whose email is still unverified
  // after a week. These are people who got invited but never confirmed.
  const staleCutoff = Date.now() - STALE_INVITATION_DAYS * 24 * 60 * 60 * 1000;
  const staleInvites = users.filter((u) => {
    if (!u.is_active) return false;
    if (u.email_verified) return false;
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

  // Error-severity activity from the last 24 hours.
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

  // Warning-severity activity (also last 24h).
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

  // Unread notifications. Severity bumps urgency.
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

  items.sort((a, b) => urgencyOrder[a.urgency] - urgencyOrder[b.urgency]);

  const visible = items.slice(0, MAX_VISIBLE);
  const hidden = items.length - visible.length;

  if (recentActivityLoading && items.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
        <p className="text-sm text-muted-foreground">Loading action queue...</p>
      </div>
    );
  }

  if (items.length === 0) {
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
    <div className="rounded-lg border bg-card p-5 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-base font-semibold text-foreground">Admin priorities</h2>
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
                className="group flex w-full items-center gap-3 rounded-md border border-border/60 bg-background/40 px-3 py-2.5 text-left transition hover:border-primary/40 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
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
