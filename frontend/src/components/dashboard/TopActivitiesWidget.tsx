import React, { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { WidgetShell } from './WidgetShell';

interface Activity {
  description: string;
  project_name: string;
  hours: number | string;
}

interface TopActivitiesWidgetProps {
  activities: Activity[];
  totalHours: number;
  onRemove: () => void;
}

const toNum = (v: string | number) => (typeof v === 'string' ? parseFloat(v) : v);

const formatHM = (h: number) => {
  const safe = Number.isFinite(h) ? h : 0;
  const hrs = Math.floor(safe);
  const mins = Math.round((safe - hrs) * 60);
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
};

export const TopActivitiesWidget: React.FC<TopActivitiesWidgetProps> = ({ activities, totalHours, onRemove }) => {
  const barsRef = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    barsRef.current.forEach((bar, i) => {
      if (!bar) return;
      const h = toNum(activities[i]?.hours ?? 0);
      const pct = totalHours > 0 ? Math.max((h / totalHours) * 100, 3) : 3;
      gsap.fromTo(bar, { width: '0%' }, { width: `${pct}%`, duration: 0.5, ease: 'power2.out', delay: i * 0.05 });
    });
  }, [activities, totalHours]);

  return (
    <WidgetShell widgetKey="activity" span={4} title="Top Activities" onRemove={onRemove}>
      {activities.length === 0 ? (
        <p className="text-sm text-muted-foreground">No activity this period.</p>
      ) : (
        <div className="space-y-3">
          {activities.slice(0, 6).map((act, i) => {
            const h = toNum(act.hours);
            return (
              <div key={`${act.description}-${i}`}>
                <div className="flex items-center justify-between gap-2 mb-1">
                  <p className="truncate text-sm text-foreground">
                    {act.description || '(no description)'}
                  </p>
                  <span className="shrink-0 font-mono text-xs text-muted-foreground">
                    {formatHM(h)}
                  </span>
                </div>
                <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    ref={(el) => { barsRef.current[i] = el; }}
                    className="h-full rounded-full bg-primary/60"
                    style={{ width: 0 }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </WidgetShell>
  );
};
