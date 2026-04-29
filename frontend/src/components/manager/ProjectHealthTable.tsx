import React from 'react';

import type { ManagerProjectHealthRow } from '@/types';

interface ProjectHealthTableProps {
  rows: ManagerProjectHealthRow[];
  isLoading?: boolean;
}

const healthClass: Record<string, string> = {
  good: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  'at-risk': 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
  'needs-attention': 'bg-red-500/15 text-red-700 dark:text-red-300',
  'not-set': 'bg-muted text-muted-foreground',
};

const healthLabel: Record<string, string> = {
  good: 'Good',
  'at-risk': 'At risk',
  'needs-attention': 'Needs attention',
  'not-set': 'Not set',
};

const formatTimeLeft = (days: number | null): { text: string; tone: 'green' | 'amber' | 'red' | 'muted' } => {
  if (days == null) return { text: 'Open', tone: 'muted' };
  if (days < -30) return { text: `${Math.abs(Math.round(days / 30))} mo over`, tone: 'red' };
  if (days < 0) return { text: `${Math.abs(days)}d over`, tone: 'red' };
  if (days <= 7) return { text: `${days} days`, tone: 'amber' };
  if (days <= 30) return { text: `${days} days`, tone: 'green' };
  if (days <= 60) return { text: '1 month', tone: 'green' };
  return { text: `${Math.round(days / 30)} mo`, tone: 'green' };
};

const toneDot: Record<string, string> = {
  green: 'bg-emerald-500',
  amber: 'bg-amber-500',
  red: 'bg-red-500',
  muted: 'bg-muted-foreground/40',
};

const formatHours = (h: string | number): string => {
  const n = typeof h === 'string' ? parseFloat(h) : h;
  if (!Number.isFinite(n)) return '0h';
  return `${n.toFixed(n % 1 === 0 ? 0 : 1)}h`;
};

const formatRemaining = (remaining: string | number | null): string => {
  if (remaining == null) return 'No budget';
  const n = typeof remaining === 'string' ? parseFloat(remaining) : remaining;
  if (!Number.isFinite(n)) return '—';
  if (n < 0) return `${formatHours(Math.abs(n))} over`;
  return `${formatHours(n)} left`;
};

export const ProjectHealthTable: React.FC<ProjectHealthTableProps> = ({ rows, isLoading }) => {
  if (isLoading && rows.length === 0) {
    return <p className="text-sm text-muted-foreground">Loading project health...</p>;
  }
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No projects with team activity in the last two weeks.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            <th className="px-2 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">Project</th>
            <th className="px-2 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">Client</th>
            <th className="px-2 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">Time left</th>
            <th className="px-2 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">Hours this week</th>
            <th className="px-2 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">Budget</th>
            <th className="px-2 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">Health</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const time = formatTimeLeft(row.days_until_end);
            const overBudget = row.budget_pct != null && row.budget_pct > 100;
            const fillPct = row.budget_pct == null ? 0 : Math.min(100, row.budget_pct);
            const fillCls = row.budget_pct == null ? 'bg-muted'
              : overBudget ? 'bg-red-500'
              : row.budget_pct > 80 ? 'bg-amber-500'
              : 'bg-emerald-500';
            return (
              <tr key={row.project_id} className="border-b border-border/60 last:border-0 hover:bg-muted/30">
                <td className="px-2 py-3 font-semibold">{row.project_name}</td>
                <td className="px-2 py-3 text-muted-foreground">{row.client_name || '—'}</td>
                <td className="px-2 py-3 font-mono text-xs">
                  <span className={`inline-block h-2 w-2 rounded-full mr-1.5 align-middle ${toneDot[time.tone]}`} />
                  {time.text}
                </td>
                <td className="px-2 py-3 font-mono text-xs">{formatHours(row.hours_this_week)}</td>
                <td className="px-2 py-3 min-w-[140px]">
                  <div className="flex items-baseline justify-between">
                    <span className={`text-xs font-bold ${overBudget ? 'text-red-600 dark:text-red-400' : ''}`}>
                      {row.budget_pct == null ? '—' : `${row.budget_pct}%`}
                    </span>
                    <span className="text-[11px] text-muted-foreground">{formatRemaining(row.budget_hours_remaining)}</span>
                  </div>
                  <div className="mt-1 h-[3px] overflow-hidden rounded-full bg-muted">
                    <div className={`h-full ${fillCls}`} style={{ width: `${fillPct}%` }} />
                  </div>
                </td>
                <td className="px-2 py-3">
                  <span className={`inline-flex items-center justify-center rounded-full px-3 py-1 text-xs font-bold min-w-[110px] ${healthClass[row.health] ?? healthClass.good}`}>
                    {healthLabel[row.health] ?? 'Good'}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
