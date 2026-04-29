import React from 'react';
import { useNavigate } from 'react-router-dom';

import type { ManagerTeamOverviewResponse } from '@/types';

interface ManagerGlanceTilesProps {
  overview: ManagerTeamOverviewResponse | undefined;
  /** Show the "Inbox" tile in slot 5 instead of project alerts. */
  ingestionEnabled?: boolean;
  pendingIngestionCount?: number;
  ingestionOldestHours?: number | null;
  /** Project-alert count, used in the 5th tile when ingestion is OFF. */
  projectAlertCount?: number;
}

type Tone = 'good' | 'warn' | 'bad' | 'info' | 'neutral';

interface Tile {
  label: string;
  value: string;
  sub: string;
  tone: Tone;
  onClick?: () => void;
}

const toneClass: Record<Tone, string> = {
  good: 'text-emerald-600 dark:text-emerald-400',
  warn: 'text-amber-600 dark:text-amber-400',
  bad: 'text-red-600 dark:text-red-400',
  info: 'text-sky-600 dark:text-sky-400',
  neutral: 'text-foreground',
};

const ageSubtitle = (hours: number | null | undefined): string => {
  if (hours == null) return 'no pending';
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
};

export const ManagerGlanceTiles: React.FC<ManagerGlanceTilesProps> = ({
  overview,
  ingestionEnabled,
  pendingIngestionCount = 0,
  ingestionOldestHours,
  projectAlertCount,
}) => {
  const navigate = useNavigate();

  // Show skeleton tiles when loading. Same shape as real ones; the user
  // doesn't see a layout shift when the data lands.
  const placeholder: Tile = { label: '...', value: '—', sub: 'loading', tone: 'neutral' };

  const tiles: Tile[] = overview ? [
    {
      label: 'Team on track',
      value: `${overview.members.filter((m) =>
        !m.is_repeatedly_late
        && !m.is_on_pto_today
        && (m.working_days_in_week === 0 || m.submitted_days >= m.working_days_in_week)
      ).length}/${overview.team_size}`,
      sub: 'as of today',
      tone: 'neutral',
    },
    {
      label: 'Approvals pending',
      value: String(overview.pending_approvals_count),
      sub: overview.pending_approvals_count === 0 ? 'inbox zero' : `oldest ${ageSubtitle(overview.pending_approvals_oldest_hours)}`,
      tone: overview.pending_approvals_count === 0 ? 'good'
            : (overview.pending_approvals_oldest_hours ?? 0) > 24 ? 'bad'
            : 'warn',
      onClick: () => navigate('/approvals'),
    },
    {
      label: 'Avg approval age',
      value: overview.pending_approvals_avg_hours == null ? '—' : `${overview.pending_approvals_avg_hours}h`,
      sub: overview.pending_approvals_avg_hours == null ? 'no pending'
            : (overview.pending_approvals_avg_hours > 24 ? 'past SLA' : 'within SLA'),
      tone: overview.pending_approvals_avg_hours == null ? 'good'
            : overview.pending_approvals_avg_hours > 24 ? 'bad' : 'good',
    },
    {
      label: 'PTO this week',
      value: String(new Set(overview.capacity_this_week.map((c) => c.user_id)).size),
      sub: `${new Set(overview.capacity_next_week.map((c) => c.user_id)).size} next week`,
      tone: 'info',
    },
    ingestionEnabled
      ? {
          label: 'Inbox',
          value: String(pendingIngestionCount),
          // ingestionOldestHours is currently optional on the manager
          // dashboard wiring. Show the age line only when we actually
          // have it; otherwise fall back to the friendlier "X awaiting
          // review" copy. Avoids the "oldest no pending" word salad
          // when the count is non-zero but age is undefined.
          sub: pendingIngestionCount === 0
            ? 'all clear'
            : ingestionOldestHours != null
              ? `oldest ${ageSubtitle(ingestionOldestHours)}`
              : `${pendingIngestionCount === 1 ? 'awaits' : 'await'} review`,
          tone: pendingIngestionCount === 0 ? 'good'
                : (ingestionOldestHours ?? 0) > 24 ? 'bad' : 'warn',
          onClick: () => navigate('/ingestion/inbox'),
        }
      : {
          label: 'Project alerts',
          value: String(projectAlertCount ?? 0),
          sub: (projectAlertCount ?? 0) === 0 ? 'all healthy' : 'needs attention',
          tone: (projectAlertCount ?? 0) === 0 ? 'good' : 'warn',
        },
  ] : [placeholder, placeholder, placeholder, placeholder, placeholder];

  return (
    <div className="grid grid-cols-2 gap-3 mb-4 md:grid-cols-5">
      {tiles.map((tile, i) => {
        const Inner = (
          <div className="rounded-lg border bg-card p-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)] transition-colors hover:bg-muted/40">
            <p className="text-[11px] uppercase tracking-[0.04em] text-muted-foreground font-semibold">{tile.label}</p>
            <p className={`mt-2 text-2xl font-bold leading-none ${toneClass[tile.tone]}`}>{tile.value}</p>
            <p className="mt-1.5 text-xs text-muted-foreground">{tile.sub}</p>
          </div>
        );
        return tile.onClick ? (
          <button
            key={`${tile.label}-${i}`}
            type="button"
            onClick={tile.onClick}
            className="text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 rounded-lg"
          >
            {Inner}
          </button>
        ) : (
          <div key={`${tile.label}-${i}`}>{Inner}</div>
        );
      })}
    </div>
  );
};
