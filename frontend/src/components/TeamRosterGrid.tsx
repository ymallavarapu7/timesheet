import React from 'react';

import type { User } from '@/types';

type RosterStatus = 'submitted' | 'grace' | 'missing';

interface RosterEntry {
  user: User;
  status: RosterStatus;
}

export interface TeamRosterGridProps {
  /** Yesterday's submission state, split into the three buckets that
   *  the team-daily-overview endpoint already returns. */
  submitted: User[];
  grace: User[];
  missing: User[];
  /** Click handler. Receives the user id; the parent decides what to
   *  do (typically: filter the dashboard to that employee's data). */
  onSelectEmployee?: (userId: number) => void;
  /** Optional currently-selected employee id so we can outline the
   *  matching chip. */
  selectedUserId?: number | null;
}

const statusOrder: Record<RosterStatus, number> = {
  missing: 0,
  grace: 1,
  submitted: 2,
};

const chipClass: Record<RosterStatus, string> = {
  submitted:
    'border-emerald-400/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 hover:border-emerald-400/70',
  grace:
    'border-amber-400/40 bg-amber-500/10 text-amber-700 dark:text-amber-300 hover:border-amber-400/70',
  missing:
    'border-red-400/40 bg-red-500/10 text-red-700 dark:text-red-300 hover:border-red-400/70',
};

const dotClass: Record<RosterStatus, string> = {
  submitted: 'bg-emerald-500',
  grace: 'bg-amber-500',
  missing: 'bg-red-500',
};

const statusLabel: Record<RosterStatus, string> = {
  submitted: 'Submitted',
  grace: 'In grace window',
  missing: 'Not submitted',
};

const initialsFor = (fullName: string): string => {
  const parts = fullName.trim().split(/\s+/);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

export const TeamRosterGrid: React.FC<TeamRosterGridProps> = ({
  submitted,
  grace,
  missing,
  onSelectEmployee,
  selectedUserId,
}) => {
  // Flatten all three buckets, then sort: missing first (most urgent),
  // grace second, submitted last. Within a bucket, alphabetical so the
  // ordering is stable across renders.
  const entries: RosterEntry[] = React.useMemo(() => {
    const all: RosterEntry[] = [
      ...missing.map((u) => ({ user: u, status: 'missing' as const })),
      ...grace.map((u) => ({ user: u, status: 'grace' as const })),
      ...submitted.map((u) => ({ user: u, status: 'submitted' as const })),
    ];
    all.sort((a, b) => {
      const so = statusOrder[a.status] - statusOrder[b.status];
      if (so !== 0) return so;
      return a.user.full_name.localeCompare(b.user.full_name);
    });
    return all;
  }, [submitted, grace, missing]);

  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No team members to display for this date.</p>
    );
  }

  const counts = {
    missing: missing.length,
    grace: grace.length,
    submitted: submitted.length,
  };

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className={`inline-block h-2 w-2 rounded-full ${dotClass.submitted}`} />
          {counts.submitted} submitted
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className={`inline-block h-2 w-2 rounded-full ${dotClass.grace}`} />
          {counts.grace} in grace window
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className={`inline-block h-2 w-2 rounded-full ${dotClass.missing}`} />
          {counts.missing} not submitted
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {entries.map(({ user, status }) => {
          const selected = selectedUserId === user.id;
          const tooltip = `${user.full_name} · ${statusLabel[status]}`;
          return (
            <button
              key={user.id}
              type="button"
              onClick={() => onSelectEmployee?.(user.id)}
              title={tooltip}
              aria-label={tooltip}
              aria-pressed={selected}
              className={`group inline-flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 ${chipClass[status]} ${selected ? 'ring-2 ring-primary ring-offset-1' : ''}`}
            >
              <span
                aria-hidden
                className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-background/40 text-[10px] font-semibold text-foreground/80 group-hover:bg-background/60"
              >
                {initialsFor(user.full_name)}
              </span>
              <span className="truncate max-w-[10rem]">{user.full_name}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
};
