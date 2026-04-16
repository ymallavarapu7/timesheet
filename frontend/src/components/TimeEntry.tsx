import React from 'react';
import { useForm } from 'react-hook-form';
import { TimeEntry } from '@/types';
import { format } from 'date-fns';
import { useUpdateTimeEntry, useDeleteTimeEntry } from '@/hooks';

interface TimeEntryFormProps {
  entry?: TimeEntry;
  projectId?: number;
  onSuccess?: (entry: TimeEntry) => void;
  onCancel?: () => void;
}

export const TimeEntryForm: React.FC<TimeEntryFormProps> = ({
  entry,
  onSuccess,
  onCancel,
}) => {
  const { register, handleSubmit, formState: { errors } } = useForm({
    defaultValues: entry ? {
      hours: entry.hours,
      description: entry.description,
    } : {
      hours: 8,
      description: '',
    },
  });

  const updateMutation = useUpdateTimeEntry(entry?.id || 0);

  type TimeEntryFormValues = {
    hours: number | string;
    description: string;
  };

  const onSubmit = async (data: TimeEntryFormValues) => {
    try {
      const result = await updateMutation.mutateAsync({
        ...data,
        hours: typeof data.hours === 'number' ? data.hours : parseFloat(data.hours),
      });
      onSuccess?.(result);
    } catch (error) {
      console.error('Error saving time entry:', error);
    }
  };

  if (!entry || (entry.status !== 'DRAFT' && entry.status !== 'REJECTED')) {
    return null;
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="bg-card p-4 rounded border">
      <div className="grid gap-4">
        <div>
          <label className="block text-sm font-medium mb-1">Hours</label>
          <input
            type="number"
            step="0.5"
            min="0.5"
            max="24"
            {...register('hours', { required: true, min: 0.5, max: 24 })}
            className="w-full px-3 py-2 border rounded"
          />
          {errors.hours && <p className="text-red-500 text-sm mt-1">Invalid hours</p>}
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Description</label>
          <textarea
            {...register('description', { required: true })}
            className="w-full px-3 py-2 border rounded"
            rows={3}
          />
          {errors.description && <p className="text-red-500 text-sm mt-1">Required</p>}
        </div>

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={updateMutation.isPending}
            className="flex-1 px-3 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
          >
            {updateMutation.isPending ? 'Saving...' : 'Save'}
          </button>
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="flex-1 px-3 py-2 bg-muted text-muted-foreground rounded hover:bg-muted/90"
            >
              Cancel
            </button>
          )}
        </div>
      </div>
    </form>
  );
};

interface TimeEntryRowProps {
  entry: TimeEntry;
  onEdit?: (entry: TimeEntry) => void;
  onRework?: (entry: TimeEntry) => void;
  onDelete?: (id: number) => void;
  onSubmit?: (ids: number[]) => void;
  showActions?: boolean;
  highlighted?: boolean;
  rowId?: string;
  /** Compact variant for nested lists (e.g. inside a grouped rejection card). */
  compact?: boolean;
  /** Hide the per-entry rejection reason (typically shown by the parent group). */
  hideRejectionReason?: boolean;
}

export const TimeEntryRow: React.FC<TimeEntryRowProps> = ({
  entry,
  onEdit,
  onRework,
  onDelete,
  onSubmit,
  showActions = true,
  highlighted = false,
  rowId,
  compact = false,
  hideRejectionReason = false,
}) => {
  const deleteMutation = useDeleteTimeEntry(entry.id);

  const handleDelete = async () => {
    if (confirm('Delete this time entry?')) {
      try {
        await deleteMutation.mutateAsync();
        onDelete?.(entry.id);
      } catch (error) {
        console.error('Error deleting entry:', error);
      }
    }
  };

  const statusColors = {
    DRAFT: 'bg-slate-100 text-slate-600',
    SUBMITTED: 'bg-slate-200 text-slate-700',
    APPROVED: 'bg-emerald-50 text-emerald-700',
    REJECTED: 'bg-red-50 text-red-700',
  };

  if (compact) {
    return (
      <div
        id={rowId}
        className={`flex items-center justify-between gap-3 rounded border bg-card px-3 py-2 text-sm ${highlighted ? 'ring-2 ring-primary border-primary' : ''}`}
      >
        <div className="min-w-0 flex-1 flex items-center gap-3">
          <span className="font-medium whitespace-nowrap">{format(new Date(entry.entry_date), 'EEE, MMM d')}</span>
          {entry.project && (
            <span className="truncate text-muted-foreground">{entry.project.name}</span>
          )}
          <span className="ml-auto whitespace-nowrap font-medium">{Number(entry.hours).toFixed(2)}h</span>
        </div>
        {showActions && (entry.status === 'DRAFT' || entry.status === 'REJECTED') && (
          <div className="flex items-center gap-1.5 shrink-0">
            {entry.status === 'DRAFT' && onSubmit && (
              <button
                onClick={() => onSubmit([entry.id])}
                className="px-2 py-1 bg-primary text-primary-foreground text-xs rounded hover:bg-primary/80"
              >
                Submit
              </button>
            )}
            <button
              onClick={() => onEdit?.(entry)}
              className="px-2 py-1 bg-slate-100 text-slate-700 text-xs rounded hover:bg-slate-200"
            >
              {entry.status === 'REJECTED' ? 'Edit & Rework' : 'Edit'}
            </button>
            <button
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
              className="px-2 py-1 bg-destructive/10 text-destructive text-xs rounded hover:bg-destructive/20 disabled:opacity-50"
            >
              {deleteMutation.isPending ? '...' : 'Delete'}
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div id={rowId} className={`border rounded p-4 bg-card ${highlighted ? 'ring-2 ring-primary border-primary' : ''}`}>
      <div className="flex items-start justify-between gap-4">
        {/* Left: date + project */}
        <div className="min-w-0">
          <p className="font-medium">{format(new Date(entry.entry_date), 'MMM d, yyyy')}</p>
          {entry.project && <p className="text-sm text-muted-foreground">{entry.project.name}</p>}
          <p className="text-sm mt-2">{entry.description}</p>
          <p className="text-sm font-medium mt-1">{entry.hours} hours</p>
          {entry.rejection_reason && !hideRejectionReason && (
            <div className="bg-red-50 border border-red-200 p-2 rounded text-sm mt-2">
              <p className="font-medium text-red-900">Rejection reason:</p>
              <p className="text-red-800">{entry.rejection_reason}</p>
            </div>
          )}
        </div>

        {/* Right: status badge + actions */}
        <div className="flex flex-col items-end gap-2 shrink-0">
          <span className={`px-2 py-1 rounded text-xs font-medium ${statusColors[entry.status]}`}>
            {entry.status}
          </span>
          {showActions && (entry.status === 'DRAFT' || entry.status === 'REJECTED') && (
            <div className="flex flex-col gap-1 w-24">
              {entry.status === 'DRAFT' && onSubmit && (
                <button
                  onClick={() => onSubmit([entry.id])}
                  className="w-full px-3 py-1.5 bg-primary text-primary-foreground text-xs rounded hover:bg-primary/80"
                >
                  Submit
                </button>
              )}
              <button
                onClick={() => onEdit?.(entry)}
                className="w-full px-3 py-1.5 bg-slate-100 text-slate-700 text-xs rounded hover:bg-slate-200"
              >
                {entry.status === 'REJECTED' ? 'Edit & Rework' : 'Edit'}
              </button>
              <button
                onClick={handleDelete}
                disabled={deleteMutation.isPending}
                className="w-full px-3 py-1.5 bg-destructive/10 text-destructive text-xs rounded hover:bg-destructive/20 disabled:opacity-50"
              >
                {deleteMutation.isPending ? '...' : 'Delete'}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
