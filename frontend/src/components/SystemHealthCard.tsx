import React from 'react';

export type SystemHealthStatus = 'healthy' | 'attention' | 'loading';

export interface SystemHealthCardProps {
  /** Service name shown on the card. */
  label: string;
  status: SystemHealthStatus;
  /** Freshness subtitle: "Last query 2s ago", "Last fetch 4h ago", "Reachable", etc. */
  subtitle: string;
  /** Optional 24-bucket sparkline. Each value is 0-1. When omitted, a flat
   *  "no data" strip renders so the card height stays consistent across the
   *  grid. The last bucket flips to amber when status is "attention" so the
   *  visual cue lines up with the chip. */
  sparkline?: number[];
}

const SPARK_BUCKETS = 24;

const statusChipClass: Record<SystemHealthStatus, string> = {
  healthy: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300 border-emerald-400/20',
  attention: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300 border-amber-400/30',
  loading: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400 border-slate-300/30',
};

const statusChipLabel: Record<SystemHealthStatus, string> = {
  healthy: 'Healthy',
  attention: 'Attention',
  loading: 'Checking…',
};

const baseBarClass: Record<SystemHealthStatus, string> = {
  healthy: 'bg-emerald-500/55 dark:bg-emerald-400/55',
  attention: 'bg-amber-500/55 dark:bg-amber-400/60',
  loading: 'bg-slate-400/40 dark:bg-slate-600/40',
};

const tipBarClass: Record<SystemHealthStatus, string> = {
  healthy: 'bg-emerald-500 dark:bg-emerald-400',
  attention: 'bg-amber-500 dark:bg-amber-400',
  loading: 'bg-slate-400 dark:bg-slate-500',
};

export const SystemHealthCard: React.FC<SystemHealthCardProps> = ({ label, status, subtitle, sparkline }) => {
  // Pad / truncate to a fixed bucket count so all cards line up.
  const buckets: number[] = React.useMemo(() => {
    const seed = sparkline && sparkline.length > 0 ? sparkline : null;
    if (!seed) return new Array(SPARK_BUCKETS).fill(0.45);
    if (seed.length === SPARK_BUCKETS) return seed;
    if (seed.length > SPARK_BUCKETS) return seed.slice(seed.length - SPARK_BUCKETS);
    const padCount = SPARK_BUCKETS - seed.length;
    return [...new Array(padCount).fill(0), ...seed];
  }, [sparkline]);

  return (
    <div className="rounded-md border border-border/60 bg-background/40 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">{label}</p>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusChipClass[status]}`}>
          {statusChipLabel[status]}
        </span>
      </div>
      <div className="mt-3 flex h-6 items-end gap-[2px]" aria-hidden>
        {buckets.map((value, i) => {
          const height = Math.max(2, Math.min(1, value) * 22);
          const isTip = status === 'attention' && i === buckets.length - 1;
          const cls = isTip ? tipBarClass[status] : baseBarClass[status];
          return (
            <span
              key={i}
              className={`w-[3px] rounded-sm ${cls}`}
              style={{ height }}
            />
          );
        })}
      </div>
    </div>
  );
};
