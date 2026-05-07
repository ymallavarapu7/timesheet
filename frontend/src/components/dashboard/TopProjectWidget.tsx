import React, { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { WidgetShell } from './WidgetShell';

interface TopProjectWidgetProps {
  projectName: string | null;
  hours: number;
  totalHours: number;
  onRemove: () => void;
}

const formatHM = (h: number) => {
  const safe = Number.isFinite(h) ? h : 0;
  const hrs = Math.floor(safe);
  const mins = Math.round((safe - hrs) * 60);
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
};

export const TopProjectWidget: React.FC<TopProjectWidgetProps> = ({
  projectName,
  hours,
  totalHours,
  onRemove,
}) => {
  const barRef = useRef<HTMLDivElement>(null);
  const pct = totalHours > 0 ? Math.min((hours / totalHours) * 100, 100) : 0;

  useEffect(() => {
    if (!barRef.current) return;
    gsap.fromTo(barRef.current, { width: '0%' }, { width: `${pct}%`, duration: 0.7, ease: 'power2.out', delay: 0.15 });
  }, [pct]);

  return (
    <WidgetShell widgetKey="tproject" span={2} title="Top Project" onRemove={onRemove}>
      <div className="flex-1 flex flex-col justify-center">
        {projectName ? (
          <>
            <p className="mb-1 truncate font-medium text-foreground">{projectName}</p>
            <div className="flex items-center gap-3">
              <span className="font-mono text-xl font-bold tracking-tight text-foreground">
                {formatHM(hours)}
              </span>
              <div className="h-1.5 w-full max-w-[100px] overflow-hidden rounded-full bg-muted">
                <div ref={barRef} className="h-full rounded-full bg-primary" />
              </div>
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">No projects logged</p>
        )}
      </div>
    </WidgetShell>
  );
};
