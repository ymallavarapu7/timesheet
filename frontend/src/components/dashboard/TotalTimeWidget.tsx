import React from 'react';
import { TrendingDown, TrendingUp } from 'lucide-react';
import { WidgetShell } from './WidgetShell';

interface TotalTimeWidgetProps {
  totalHours: number;
  prevWeekHours?: number;
  onRemove: () => void;
}

const formatHM = (h: number) => {
  const safe = Number.isFinite(h) ? h : 0;
  const hrs = Math.floor(safe);
  const mins = Math.round((safe - hrs) * 60);
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
};

export const TotalTimeWidget: React.FC<TotalTimeWidgetProps> = ({ totalHours, prevWeekHours, onRemove }) => {
  const delta = prevWeekHours != null && prevWeekHours > 0
    ? ((totalHours - prevWeekHours) / prevWeekHours) * 100
    : null;

  return (
    <WidgetShell widgetKey="total" span={3} title="Total Time" onRemove={onRemove}>
      <div className="flex-1 flex flex-col justify-center">
        <div className="relative z-10 flex items-end justify-between gap-3">
          <span className="font-mono text-4xl font-semibold tracking-tight text-foreground">
            {formatHM(totalHours)}
          </span>
          {delta !== null && (
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                delta >= 0
                  ? 'bg-primary/15 text-primary'
                  : 'bg-destructive/15 text-destructive'
              }`}
            >
              {delta >= 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
              {Math.abs(delta).toFixed(0)}%
            </span>
          )}
        </div>
        <p className="relative z-10 mt-1 text-xs text-muted-foreground">this week</p>
      </div>
    </WidgetShell>
  );
};
