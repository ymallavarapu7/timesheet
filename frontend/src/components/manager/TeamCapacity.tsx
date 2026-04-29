import React from 'react';

import type { ManagerTeamCapacityEntry } from '@/types';

interface TeamCapacityProps {
  teamSize: number;
  thisWeek: ManagerTeamCapacityEntry[];
  nextWeek: ManagerTeamCapacityEntry[];
}

const Section: React.FC<{ title: string; rows: ManagerTeamCapacityEntry[]; teamSize: number }> = ({ title, rows, teamSize }) => {
  // Headcount available = team size minus distinct people with any
  // PTO in the window. Distinct because one person can have multiple
  // leave-type rows but they only consume one seat at a time.
  const distinctOut = new Set(rows.map((r) => r.user_id)).size;
  const available = Math.max(0, teamSize - distinctOut);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="text-xs text-muted-foreground">
          {available}/{teamSize} available
        </p>
      </div>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No PTO scheduled.</p>
      ) : (
        <ul className="space-y-1.5">
          {rows.map((row) => (
            <li
              key={`${row.user_id}-${row.leave_type}`}
              className="flex items-center justify-between rounded-md border border-border/60 bg-background/40 px-3 py-2 text-xs"
            >
              <span className="truncate text-foreground">{row.full_name}</span>
              <span className="ml-2 inline-flex items-center gap-2 text-muted-foreground">
                <span className="rounded-sm bg-muted/60 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide">{row.leave_type}</span>
                <span>
                  {row.days_in_window} {row.days_in_window === 1 ? 'day' : 'days'}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export const TeamCapacity: React.FC<TeamCapacityProps> = ({ teamSize, thisWeek, nextWeek }) => {
  return (
    <div className="rounded-lg border bg-card p-5 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">Team capacity</h2>
        <span className="text-xs text-muted-foreground">Approved + pending PTO</span>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Section title="This week" rows={thisWeek} teamSize={teamSize} />
        <Section title="Next week" rows={nextWeek} teamSize={teamSize} />
      </div>
    </div>
  );
};
