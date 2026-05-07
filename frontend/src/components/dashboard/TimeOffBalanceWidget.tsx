import React from 'react';
import { Palmtree, Stethoscope, Home } from 'lucide-react';
import { WidgetShell } from './WidgetShell';

interface TimeOffBalanceWidgetProps {
  annual: number;
  sick: number;
  wfh: number;
  onRemove: () => void;
}

const BalanceRow: React.FC<{ icon: React.ReactNode; label: string; days: number }> = ({ icon, label, days }) => (
  <div className="flex items-center gap-3 rounded-lg bg-muted/40 px-3 py-2.5">
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
      {icon}
    </div>
    <div className="flex-1">
      <p className="text-sm font-medium text-foreground">{label}</p>
    </div>
    <span className="font-mono text-lg font-semibold text-foreground">{days}</span>
    <span className="text-xs text-muted-foreground">days</span>
  </div>
);

export const TimeOffBalanceWidget: React.FC<TimeOffBalanceWidgetProps> = ({
  annual,
  sick,
  wfh,
  onRemove,
}) => {
  return (
    <WidgetShell widgetKey="timeoff" span={4} title="Time Off Balance" onRemove={onRemove}>
      <div className="space-y-2">
        <BalanceRow icon={<Palmtree className="h-4 w-4" />} label="Annual Leave" days={annual} />
        <BalanceRow icon={<Stethoscope className="h-4 w-4" />} label="Sick Leave" days={sick} />
        <BalanceRow icon={<Home className="h-4 w-4" />} label="WFH Days" days={wfh} />
      </div>
    </WidgetShell>
  );
};
