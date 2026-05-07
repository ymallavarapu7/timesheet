import React from 'react';
import { WidgetShell } from './WidgetShell';

const PROJECT_COLORS = ['#7b5748', '#4f772d', '#355070', '#bc6c25', '#2a9d8f', '#6d597a', '#e76f51', '#457b9d'];

interface ProjectBreakdown {
  project_id: number;
  project_name: string;
  hours: number | string;
  percentage: number;
}

interface ProjectsBreakdownWidgetProps {
  projects: ProjectBreakdown[];
  onRemove: () => void;
}

const toNum = (v: string | number) => (typeof v === 'string' ? parseFloat(v) : v);

const formatHM = (h: number) => {
  const safe = Number.isFinite(h) ? h : 0;
  const hrs = Math.floor(safe);
  const mins = Math.round((safe - hrs) * 60);
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
};

export const ProjectsBreakdownWidget: React.FC<ProjectsBreakdownWidgetProps> = ({ projects, onRemove }) => {
  return (
    <WidgetShell widgetKey="projects" span={4} title="Projects" onRemove={onRemove}>
      {projects.length === 0 ? (
        <p className="text-sm text-muted-foreground">No projects this period.</p>
      ) : (
        <div className="space-y-3">
          {projects.map((proj, i) => {
            const h = toNum(proj.hours);
            const color = PROJECT_COLORS[i % PROJECT_COLORS.length];
            return (
              <div key={proj.project_id} className="flex items-center gap-3">
                <div className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />
                <span className="flex-1 truncate text-sm text-foreground">{proj.project_name}</span>
                <span className="shrink-0 font-mono text-xs text-muted-foreground">{formatHM(h)}</span>
                <span className="shrink-0 w-10 text-right text-xs text-muted-foreground">
                  {proj.percentage.toFixed(0)}%
                </span>
              </div>
            );
          })}
        </div>
      )}
    </WidgetShell>
  );
};
