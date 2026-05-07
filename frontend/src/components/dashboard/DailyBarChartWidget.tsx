import React, { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { format, isToday, parseISO } from 'date-fns';
import { WidgetShell } from './WidgetShell';

interface DayData {
  entry_date: string;
  hours: number | string;
  formatted_date: string;
}

interface DailyBarChartWidgetProps {
  data: DayData[];
  onRemove: () => void;
}

const toNum = (v: string | number) => (typeof v === 'string' ? parseFloat(v) : v);

const formatHM = (h: number) => {
  const safe = Number.isFinite(h) ? h : 0;
  const hrs = Math.floor(safe);
  const mins = Math.round((safe - hrs) * 60);
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
};

export const DailyBarChartWidget: React.FC<DailyBarChartWidgetProps> = ({ data, onRemove }) => {
  const barsRef = useRef<(HTMLDivElement | null)[]>([]);
  const maxValue = Math.max(...data.map((d) => toNum(d.hours)), 0.01);

  useEffect(() => {
    barsRef.current.forEach((bar, i) => {
      if (!bar) return;
      const h = toNum(data[i]?.hours ?? 0);
      const pct = h <= 0 ? 1 : Math.max((h / maxValue) * 100, 4);
      gsap.fromTo(bar, { height: '0%' }, { height: `${pct}%`, duration: 0.5, ease: 'power2.out', delay: i * 0.06 });
    });
  }, [data, maxValue]);

  return (
    <WidgetShell widgetKey="barchart" span={8} title="Daily Breakdown" onRemove={onRemove}>
      <div className="flex items-end gap-3 h-52">
        {data.map((day, i) => {
          const h = toNum(day.hours);
          const today = isToday(parseISO(day.entry_date));
          const [weekday] = day.formatted_date.split(', ');

          return (
            <div key={day.entry_date} className="flex flex-1 flex-col items-center justify-end h-full gap-1">
              <span className="font-mono text-[11px] text-muted-foreground">{formatHM(h)}</span>
              <div className="relative w-full flex-1 flex items-end justify-center">
                <div
                  ref={(el) => { barsRef.current[i] = el; }}
                  className={`w-full max-w-[72px] rounded-t-md transition-colors ${
                    today ? 'bg-primary' : 'bg-muted-foreground/20'
                  }`}
                  style={{ height: 0 }}
                />
              </div>
              <span className={`text-xs font-medium ${today ? 'text-primary' : 'text-foreground'}`}>
                {weekday}
              </span>
              <span className="text-[10px] text-muted-foreground">
                {format(parseISO(day.entry_date), 'MMM d')}
              </span>
            </div>
          );
        })}
      </div>
    </WidgetShell>
  );
};
