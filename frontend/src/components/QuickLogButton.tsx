import React from 'react';
import { Plus } from 'lucide-react';

import { useCreateTimeEntry, useProjects } from '@/hooks';
import type { Project } from '@/types';

interface QuickLogButtonProps {
  /** Optional className for outer wrapper. */
  className?: string;
}

const todayISO = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const yesterdayISO = (): string => {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const todayLabel = (): string => new Date().toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
const yesterdayLabel = (): string => {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
};

export const QuickLogButton: React.FC<QuickLogButtonProps> = ({ className }) => {
  const [open, setOpen] = React.useState(false);
  const [projectId, setProjectId] = React.useState<string>('');
  const [hours, setHours] = React.useState<string>('');
  const [description, setDescription] = React.useState<string>('');
  const [day, setDay] = React.useState<'today' | 'yesterday'>('today');
  const [error, setError] = React.useState<string | null>(null);
  const [savedFlash, setSavedFlash] = React.useState<boolean>(false);
  const projectInputRef = React.useRef<HTMLSelectElement>(null);

  // We always fetch the active projects (small payload, cached by the
  // hook). Gating on `open` would mean a noticeable wait the first
  // time the popover opens.
  const { data: projects = [] } = useProjects({ active_only: true, limit: 500 });
  const create = useCreateTimeEntry();

  const reset = () => {
    setProjectId('');
    setHours('');
    setDescription('');
    setDay('today');
    setError(null);
  };

  const close = () => {
    setOpen(false);
    setError(null);
  };

  // Esc closes; first focus lands on the project select.
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', onKey);
    const t = window.setTimeout(() => projectInputRef.current?.focus(), 0);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.clearTimeout(t);
    };
  }, [open]);

  const submit = async () => {
    setError(null);
    const pid = Number(projectId);
    const h = Number(hours);
    if (!Number.isInteger(pid) || pid <= 0) {
      setError('Pick a project.');
      return;
    }
    if (!Number.isFinite(h) || h <= 0 || h > 24) {
      setError('Hours must be between 0 and 24.');
      return;
    }
    if (Math.round(h * 2) !== h * 2) {
      setError('Hours must be in 0.5 increments.');
      return;
    }
    try {
      await create.mutateAsync({
        project_id: pid,
        entry_date: day === 'today' ? todayISO() : yesterdayISO(),
        hours: h,
        description: description.trim(),
        is_billable: true,
      });
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 1200);
      reset();
      close();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Could not log time.';
      setError(msg);
    }
  };

  return (
    <div className={className}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
      >
        <Plus className="h-4 w-4" />
        Log time
      </button>

      {savedFlash && (
        <span className="ml-2 text-xs font-medium text-emerald-600 dark:text-emerald-400">Saved</span>
      )}

      {open && (
        <>
          <div className="fixed inset-0 z-50" role="presentation" onClick={close} />
          <div
            role="dialog"
            aria-label="Quick log time"
            className="absolute right-0 z-[60] mt-2 w-[360px] rounded-xl border border-border bg-card p-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <h4 className="text-sm font-semibold text-foreground">
                Quick log
                <span className="ml-2 font-normal text-muted-foreground">{day === 'today' ? todayLabel() : yesterdayLabel()}</span>
              </h4>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setDay((d) => (d === 'today' ? 'yesterday' : 'today'))}
                  className="text-[11px] font-medium text-primary hover:underline"
                >
                  {day === 'today' ? 'Switch to yesterday' : 'Switch to today'}
                </button>
                <button type="button" onClick={close} aria-label="Close" className="text-muted-foreground hover:text-foreground">
                  ×
                </button>
              </div>
            </div>

            <div className="space-y-2">
              <select
                ref={projectInputRef}
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value="">Pick a project</option>
                {(projects as Project[]).map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
              <input
                type="number"
                min={0}
                max={24}
                step={0.5}
                inputMode="decimal"
                placeholder="Hours (e.g. 1.5)"
                value={hours}
                onChange={(e) => setHours(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <input
                type="text"
                placeholder="Description (optional)"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    void submit();
                  }
                }}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              />
              {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
              <button
                type="button"
                onClick={submit}
                disabled={create.isPending}
                className="w-full rounded-md bg-primary py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-60"
              >
                {create.isPending ? 'Logging...' : 'Log'}
              </button>
              <p className="text-[11px] text-muted-foreground">Tab through fields. Enter to log. Esc to close.</p>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
