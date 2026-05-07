import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { useTimer } from '@/hooks/useTimer';
import { formatElapsed } from './TopbarTimer';
import { useProjects, useTasks, useCreateTimeEntry } from '@/hooks/useData';
import { cn } from '@/lib/utils';
import { format } from 'date-fns';

export const LogEntryModal: React.FC = () => {
  const { status, elapsedMs, projectId, taskId, notes, discard, startTimestamp, setProject, setTask, setNotes } = useTimer();
  const { data: projects = [], isLoading: projectsLoading } = useProjects({ active_only: true, limit: 500 });
  const { data: tasks = [] } = useTasks(projectId ? { project_id: projectId, active_only: true } : undefined);
  const createMutation = useCreateTimeEntry();

  const [showError, setShowError] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  if (status !== 'stopped') return null;

  const totalHours = Number((elapsedMs / 3600000).toFixed(2)) || 0.01;
  const isTooShort = elapsedMs < 60000;

  const handleSave = () => {
    if (!projectId) {
      setShowError(true);
      return;
    }
    setSaveError(null);

    createMutation.mutate({
      project_id: projectId,
      task_id: taskId || undefined,
      description: notes || (tasks?.find((t: any) => t.id === taskId)?.name) || 'Logged time',
      hours: totalHours,
      entry_date: new Date().toISOString().split('T')[0]
    }, {
      onSuccess: () => {
        discard();
        const bc = new BroadcastChannel('acufy_timer');
        bc.postMessage({ type: 'REFRESH_MY_TIME' });
        bc.close();
      },
      onError: (err: any) => {
        const msg = err?.response?.data?.detail || err?.message || 'Failed to save time entry';
        setSaveError(typeof msg === 'string' ? msg : JSON.stringify(msg));
      }
    });
  };

  const selectedProject = projects?.find((p: any) => p.id === projectId);
  const selectedTask = tasks?.find((t: any) => t.id === taskId);

  const startTimeStr = startTimestamp ? format(new Date(startTimestamp), "EEE, MMM d · hh:mm a") : format(new Date(), "EEE, MMM d · hh:mm a");
  const endTimeStr = format(new Date(), "hh:mm a");

  return createPortal(
    <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
      <div className="w-full max-w-[520px] max-h-[90vh] rounded-2xl border border-border bg-card shadow-2xl overflow-hidden flex flex-col">
        <div className="flex justify-between items-center px-6 py-4 border-b border-border">
          <h2 className="text-xl font-bold tracking-tight">Log time entry</h2>
          <button onClick={discard} className="text-muted-foreground hover:text-foreground transition">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6 flex-1 overflow-y-auto">
          <div>
            <div className="flex items-center gap-2 text-muted-foreground font-medium mb-1">
              <span>⏱</span> Total time tracked
            </div>
            <div className="text-4xl font-mono font-bold tracking-tight text-foreground">
              {formatElapsed(elapsedMs)}
            </div>
            <div className="text-sm text-muted-foreground mt-1">
              {startTimeStr} – {endTimeStr}
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-semibold mb-1.5">Project <span className="text-destructive">*</span></label>
              {projectsLoading ? (
                <div className="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm text-muted-foreground">
                  Loading projects...
                </div>
              ) : (
                <select
                  value={projectId ?? ''}
                  onChange={(e) => {
                    const val = e.target.value;
                    setProject(val ? Number(val) : null);
                    setTask(null);
                    setShowError(false);
                    setSaveError(null);
                  }}
                  className={cn(
                    "w-full rounded-xl border bg-background px-3 py-2.5 text-sm focus:ring-2 focus:ring-primary focus:outline-none transition-all appearance-none cursor-pointer",
                    showError && !projectId ? "border-destructive focus:ring-destructive" : "border-border/60"
                  )}
                >
                  <option value="">Select a project...</option>
                  {(projects ?? []).map((p: any) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              )}
              {showError && !projectId && <p className="text-destructive text-xs mt-1">Project is required</p>}
            </div>

            <div>
              <label className="block text-sm font-semibold mb-1.5">Task</label>
              <select
                value={taskId ?? ''}
                onChange={(e) => {
                  const val = e.target.value;
                  setTask(val ? Number(val) : null);
                }}
                disabled={!projectId}
                className="w-full rounded-xl border border-border/60 bg-background px-3 py-2.5 text-sm focus:ring-2 focus:ring-primary focus:outline-none transition-all disabled:opacity-50 appearance-none cursor-pointer"
              >
                <option value="">No specific task</option>
                {(tasks ?? []).map((t: any) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-semibold mb-1.5">Notes (optional)</label>
              <textarea
                rows={3}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                className="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm focus:ring-2 focus:ring-primary focus:outline-none transition-all"
                placeholder="What did you work on?"
              />
            </div>
          </div>

          <div className="pt-2">
            <h3 className="text-xs font-bold uppercase tracking-widest text-muted-foreground/70 mb-3">Entry preview</h3>
            <div className="rounded-xl border border-border/50 bg-muted/20 p-4">
              <div className="flex items-center gap-2 font-semibold text-foreground mb-1">
                <div className="w-3 h-3 rounded-sm bg-primary/20 border border-primary/50" />
                {selectedProject?.name || 'Unknown Project'}
              </div>
              <div className="text-sm text-muted-foreground mb-2">
                {selectedTask?.name || 'General Task'} · {Math.floor(elapsedMs / 3600000)}h {Math.floor((elapsedMs % 3600000) / 60000)}m
              </div>
              <div className="text-sm text-muted-foreground/80 mb-2">
                {startTimeStr.split('·')[0].trim()}, {startTimeStr.split('·')[1]?.trim()} – {endTimeStr}
              </div>
              {notes && (
                <div className="text-sm italic text-foreground border-l-2 border-primary/40 pl-2">
                  "{notes}"
                </div>
              )}
            </div>
          </div>

          {isTooShort && (
            <div className="rounded-lg bg-amber-500/10 text-amber-500 p-3 text-sm font-medium border border-amber-500/20">
              Timer ran for less than 1 minute. Are you sure you want to log this?
            </div>
          )}

          {saveError && (
            <div className="rounded-lg bg-destructive/10 text-destructive p-3 text-sm font-medium border border-destructive/20">
              {saveError}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between px-6 py-4 border-t border-border bg-muted/10">
          <button
            onClick={() => {
              if (window.confirm("Discard this entry?")) {
                discard();
              }
            }}
            className="text-sm font-medium text-muted-foreground hover:text-foreground transition"
            disabled={createMutation.isPending}
          >
            Discard
          </button>
          <button
            onClick={handleSave}
            disabled={createMutation.isPending}
            className="rounded-xl bg-primary px-5 py-2.5 text-sm font-bold text-primary-foreground transition-all hover:bg-primary/90 disabled:opacity-50"
          >
            {createMutation.isPending ? 'Saving...' : 'Save to My Time →'}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
};
