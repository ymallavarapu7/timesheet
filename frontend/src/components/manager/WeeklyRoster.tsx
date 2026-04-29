import React from 'react';

import type { ManagerTeamMemberStatus } from '@/types';

interface WeeklyRosterProps {
  members: ManagerTeamMemberStatus[];
  onSelectEmployee?: (userId: number) => void;
  selectedUserId?: number | null;
}

type RowState = 'on-track' | 'behind' | 'pto' | 'critical';

const stateClass: Record<RowState, string> = {
  'on-track': 'border-emerald-400/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 hover:border-emerald-400/70',
  behind: 'border-amber-400/40 bg-amber-500/10 text-amber-700 dark:text-amber-300 hover:border-amber-400/70',
  pto: 'border-sky-400/40 bg-sky-500/10 text-sky-700 dark:text-sky-300 hover:border-sky-400/70',
  critical: 'border-red-400/40 bg-red-500/10 text-red-700 dark:text-red-300 hover:border-red-400/70',
};

const stateOrder: Record<RowState, number> = {
  critical: 0,
  behind: 1,
  pto: 2,
  'on-track': 3,
};

const stateLabel: Record<RowState, string> = {
  'on-track': 'On track',
  behind: 'Behind',
  pto: 'On PTO',
  critical: 'Critical',
};

const initialsFor = (fullName: string): string => {
  const parts = fullName.trim().split(/\s+/);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

const classify = (member: ManagerTeamMemberStatus): RowState => {
  // Critical: repeatedly-late pattern wins — surface the pattern even if
  // the rest looks fine, because the manager needs to act on the pattern.
  if (member.is_repeatedly_late) return 'critical';
  if (member.is_on_pto_today) return 'pto';
  if (member.working_days_in_week === 0) return 'on-track';
  if (member.submitted_days >= member.working_days_in_week) return 'on-track';
  return 'behind';
};

export const WeeklyRoster: React.FC<WeeklyRosterProps> = ({ members, onSelectEmployee, selectedUserId }) => {
  if (members.length === 0) {
    return <p className="text-sm text-muted-foreground">No team members to display.</p>;
  }

  const enriched = React.useMemo(
    () => members.map((m) => ({ member: m, state: classify(m) })),
    [members],
  );

  const sorted = [...enriched].sort((a, b) => {
    const so = stateOrder[a.state] - stateOrder[b.state];
    if (so !== 0) return so;
    return a.member.full_name.localeCompare(b.member.full_name);
  });

  const counts = enriched.reduce(
    (acc, { state }) => {
      acc[state] += 1;
      return acc;
    },
    { 'on-track': 0, behind: 0, pto: 0, critical: 0 } as Record<RowState, number>,
  );

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
          {counts.critical} critical
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-amber-500" />
          {counts.behind} behind
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-sky-500" />
          {counts.pto} on PTO
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
          {counts['on-track']} on track
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {sorted.map(({ member, state }) => {
          const ratio = `${member.submitted_days}/${member.working_days_in_week || 0}`;
          const tooltip = `${member.full_name} · ${stateLabel[state]} · ${ratio} days submitted`;
          const selected = selectedUserId === member.user_id;
          return (
            <button
              key={member.user_id}
              type="button"
              onClick={() => onSelectEmployee?.(member.user_id)}
              title={tooltip}
              aria-label={tooltip}
              aria-pressed={selected}
              className={`group inline-flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 ${stateClass[state]} ${selected ? 'ring-2 ring-primary ring-offset-1' : ''}`}
            >
              <span aria-hidden className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-background/40 text-[10px] font-semibold text-foreground/80 group-hover:bg-background/60">
                {initialsFor(member.full_name)}
              </span>
              <span className="truncate max-w-[10rem]">{member.full_name}</span>
              <span className="rounded-sm border border-border/40 bg-background/30 px-1 py-0.5 text-[10px] font-mono text-foreground/80">
                {ratio}
              </span>
              {member.is_repeatedly_late && (
                <span className="rounded-sm bg-red-600/20 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide text-red-700 dark:text-red-300">
                  Late
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};
