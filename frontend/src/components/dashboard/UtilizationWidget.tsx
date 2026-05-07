import React, { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { WidgetShell } from './WidgetShell';

interface UtilizationWidgetProps {
  totalHours: number;
  targetHours?: number;
  onRemove: () => void;
}

export const UtilizationWidget: React.FC<UtilizationWidgetProps> = ({
  totalHours,
  targetHours = 40,
  onRemove,
}) => {
  const circleRef = useRef<SVGCircleElement>(null);
  const pct = targetHours > 0 ? Math.min((totalHours / targetHours) * 100, 100) : 0;

  const size = 56;
  const strokeWidth = 5;
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;

  useEffect(() => {
    if (!circleRef.current) return;
    const offset = circumference - (pct / 100) * circumference;
    gsap.fromTo(
      circleRef.current,
      { strokeDashoffset: circumference },
      { strokeDashoffset: offset, duration: 1, ease: 'power3.out', delay: 0.1 }
    );
  }, [pct, circumference]);

  return (
    <WidgetShell widgetKey="util" span={2} title="Utilization" onRemove={onRemove}>
      <div className="flex-1 flex flex-col justify-center">
        <div className="flex items-center justify-between gap-2">
          <div>
            <span className="font-mono text-3xl font-semibold text-foreground">
              {pct.toFixed(0)}%
            </span>
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground mt-0.5">
              of {targetHours}h target
            </p>
          </div>

          <div className="relative" style={{ width: size, height: size }}>
            <svg width={size} height={size} className="-rotate-90 transform">
              <circle
                cx={size / 2}
                cy={size / 2}
                r={radius}
                className="stroke-muted fill-none"
                strokeWidth={strokeWidth}
              />
              <circle
                ref={circleRef}
                cx={size / 2}
                cy={size / 2}
                r={radius}
                className="stroke-primary fill-none transition-colors"
                strokeWidth={strokeWidth}
                strokeDasharray={circumference}
                strokeDashoffset={circumference}
                strokeLinecap="round"
              />
            </svg>
          </div>
        </div>
      </div>
    </WidgetShell>
  );
};
