import React, { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { Flame } from 'lucide-react';
import { WidgetShell } from './WidgetShell';

interface OvertimeWidgetProps {
  totalHours: number;
  targetHours?: number;
  onRemove: () => void;
}

export const OvertimeWidget: React.FC<OvertimeWidgetProps> = ({ totalHours, targetHours = 40, onRemove }) => {
  const iconRef = useRef<HTMLDivElement>(null);
  const overtime = Math.max(0, totalHours - targetHours);
  const isOvertime = overtime > 0;

  useEffect(() => {
    if (isOvertime && iconRef.current) {
      gsap.to(iconRef.current, {
        y: -3,
        scale: 1.1,
        duration: 0.8,
        repeat: -1,
        yoyo: true,
        ease: 'power1.inOut'
      });
    }
  }, [isOvertime]);

  return (
    <WidgetShell widgetKey="overtime" span={2} title="Overtime" onRemove={onRemove}>
      <div className="flex-1 flex flex-col justify-center">
        <div className="flex flex-col items-start gap-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-3xl font-semibold text-foreground">
              {overtime > 0 ? `+${overtime.toFixed(1)}h` : '0h'}
            </span>
            {isOvertime && (
              <div ref={iconRef} className="text-orange-500">
                <Flame className="h-5 w-5" />
              </div>
            )}
          </div>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground mt-1">
            {isOvertime ? 'beyond 40h target' : 'no overtime yet'}
          </p>
        </div>

        {isOvertime && (
          <div className="mt-3 rounded-md bg-orange-500/10 px-2 py-1.5 border border-orange-500/20">
            <p className="text-[10px] font-medium text-orange-600 dark:text-orange-400">
              Great hustle! Remember to avoid burnout.
            </p>
          </div>
        )}
      </div>
    </WidgetShell>
  );
};
