import React from 'react';
import { WidgetShell } from './WidgetShell';

interface TodayTimeWidgetProps {
  todayHours: number;
  onRemove: () => void;
}

const formatHM = (h: number) => {
  const safe = Number.isFinite(h) ? h : 0;
  const hrs = Math.floor(safe);
  const mins = Math.round((safe - hrs) * 60);
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
};

export const TodayTimeWidget: React.FC<TodayTimeWidgetProps> = ({ todayHours, onRemove }) => {
  const isTracking = Boolean(localStorage.getItem('acufy_active_timer_start'));

  return (
    <WidgetShell widgetKey="today" span={2} title="Today" onRemove={onRemove}>
      {isTracking && (
        <div className="absolute inset-0 rounded-xl ring-2 ring-primary/40 shadow-[0_0_15px_rgba(var(--primary),0.3)] pointer-events-none animate-pulse" />
      )}
      <div className="flex-1 flex flex-col justify-center">
        <div className="flex items-center gap-3">
          <span className="font-mono text-3xl font-semibold text-foreground">
            {formatHM(todayHours)}
          </span>
          {isTracking && (
            <span className="relative flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75"></span>
              <span className="relative inline-flex h-3 w-3 rounded-full bg-primary"></span>
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {isTracking ? 'currently tracking' : 'hours logged today'}
        </p>
      </div>
    </WidgetShell>
  );
};
