import React from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, ArrowRight, Calendar, CheckCircle2, ClipboardList, RotateCcw } from 'lucide-react';

type Urgency = 'urgent' | 'warn' | 'info';

interface PriorityItem {
  id: string;
  urgency: Urgency;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  detail: string;
  cta: string;
  onClick: () => void;
}

interface ManagerPrioritiesProps {
  pendingApprovalsCount: number;
  pendingTimeOffCount: number;
  rejectedRecentCount: number;
  /** When the priorities query is still loading. */
  isLoading?: boolean;
}

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

export const ManagerPriorities: React.FC<ManagerPrioritiesProps> = ({
  pendingApprovalsCount,
  pendingTimeOffCount,
  rejectedRecentCount,
  isLoading,
}) => {
  const navigate = useNavigate();
  const items: PriorityItem[] = [];

  if (pendingApprovalsCount > 0) {
    // Approvals scale: small = info, growing = warn, large = urgent.
    // The thresholds are intentionally tighter than admin's because a
    // single manager's queue is smaller in absolute size.
    const urgency: Urgency =
      pendingApprovalsCount >= 10 ? 'urgent'
      : pendingApprovalsCount >= 4 ? 'warn'
      : 'info';
    items.push({
      id: 'pending-approvals',
      urgency,
      icon: ClipboardList,
      title: `${pendingApprovalsCount} timesheet ${pendingApprovalsCount === 1 ? 'entry' : 'entries'} awaiting your approval`,
      detail: 'Review and approve so the time can flow through to billing.',
      cta: 'Review',
      onClick: () => navigate('/approvals'),
    });
  }

  if (pendingTimeOffCount > 0) {
    items.push({
      id: 'pending-time-off',
      urgency: pendingTimeOffCount >= 5 ? 'warn' : 'info',
      icon: Calendar,
      title: `${pendingTimeOffCount} time-off ${pendingTimeOffCount === 1 ? 'request' : 'requests'} awaiting your decision`,
      detail: 'Approve or push back so people can plan around it.',
      cta: 'Open',
      onClick: () => navigate('/time-off-approvals'),
    });
  }

  if (rejectedRecentCount > 0) {
    // Rejections in the current week need follow-up: did the employee
    // fix and resubmit, or is it still stuck? Always warn.
    items.push({
      id: 'rejected-recent',
      urgency: 'warn',
      icon: RotateCcw,
      title: `${rejectedRecentCount} rejected ${rejectedRecentCount === 1 ? 'entry' : 'entries'} this week`,
      detail: 'Make sure the employee fixed and resubmitted; chase if not.',
      cta: 'Inspect',
      onClick: () => navigate('/approvals?filter=rejected'),
    });
  }

  items.sort((a, b) => urgencyOrder[a.urgency] - urgencyOrder[b.urgency]);

  if (isLoading && items.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-5 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
        <p className="text-sm text-muted-foreground">Loading priorities...</p>
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
            <p className="text-sm font-semibold text-foreground">Nothing on your plate</p>
            <p className="text-xs text-muted-foreground">No approvals, no time-off requests, no recent rejections.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-5 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">Manager priorities</h2>
        <span className="text-xs text-muted-foreground">
          {items.length} {items.length === 1 ? 'item' : 'items'}
        </span>
      </div>
      <ul className="space-y-2">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={item.onClick}
                className="group flex w-full items-center gap-3 rounded-md border border-border/60 bg-background/40 px-3 py-3 text-left transition hover:border-primary/40 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
              >
                <span aria-hidden className={`inline-block h-2 w-2 shrink-0 rounded-full ${urgencyDot[item.urgency]}`} />
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
    </div>
  );
};
