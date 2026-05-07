import React, { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { WidgetShell } from './WidgetShell';

interface ProductivityWidgetProps {
  totalHours: number;
  billableHours: number;
  onRemove: () => void;
}

export const ProductivityWidget: React.FC<ProductivityWidgetProps> = ({ totalHours, billableHours, onRemove }) => {
  const barRef = useRef<HTMLDivElement>(null);
  const billablePct = totalHours > 0 ? (billableHours / totalHours) * 100 : 0;
  const nonBillablePct = 100 - billablePct;

  useEffect(() => {
    if (barRef.current) {
      gsap.fromTo(barRef.current, { width: '0%' }, { width: `${billablePct}%`, duration: 0.8, ease: 'power2.out', delay: 0.2 });
    }
  }, [billablePct]);

  return (
    <WidgetShell widgetKey="productivity" span={4} title="Productivity Ratio" onRemove={onRemove}>
      <div className="flex-1 flex flex-col justify-center">
        <div className="flex items-end justify-between mb-3">
          <div>
            <span className="font-mono text-3xl font-semibold text-foreground">
              {billablePct.toFixed(0)}%
            </span>
            <span className="ml-2 text-xs font-medium text-primary uppercase tracking-widest">
              Billable
            </span>
          </div>
        </div>

        <div className="h-3 w-full overflow-hidden rounded-full bg-muted relative flex">
          <div
            ref={barRef}
            className="h-full bg-primary transition-all"
            style={{ width: '0%' }}
          />
          <div
            className="h-full bg-muted-foreground/30 transition-all"
            style={{ width: `${nonBillablePct}%` }}
          />
        </div>

        <div className="mt-3 flex justify-between text-xs font-medium">
          <span className="text-primary">{billableHours.toFixed(1)}h</span>
          <span className="text-muted-foreground">{(totalHours - billableHours).toFixed(1)}h</span>
        </div>
      </div>
    </WidgetShell>
  );
};
