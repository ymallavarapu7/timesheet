import React from 'react';
import { Trash2, X } from 'lucide-react';

interface BulkSelectBarProps {
  selectedCount: number;
  totalCount: number;
  onSelectAll: () => void;
  onClearSelection: () => void;
  onDelete: () => void;
  isDeleting?: boolean;
  itemLabel?: string;
}

export const BulkSelectBar: React.FC<BulkSelectBarProps> = ({
  selectedCount,
  totalCount,
  onSelectAll,
  onClearSelection,
  onDelete,
  isDeleting = false,
  itemLabel = 'item',
}) => {
  if (selectedCount === 0) return null;

  const plural = selectedCount === 1 ? itemLabel : `${itemLabel}s`;

  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-primary/20 bg-primary/5 px-4 py-2.5">
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium text-foreground">
          {selectedCount} {plural} selected
        </span>
        {selectedCount < totalCount && (
          <button
            type="button"
            onClick={onSelectAll}
            className="text-xs font-medium text-primary hover:text-primary/80 transition"
          >
            Select all {totalCount}
          </button>
        )}
        <button
          type="button"
          onClick={onClearSelection}
          className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground transition"
        >
          <X className="h-3 w-3" />
          Clear
        </button>
      </div>
      <button
        type="button"
        onClick={onDelete}
        disabled={isDeleting}
        className="inline-flex items-center gap-1.5 rounded-lg bg-destructive px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-destructive/90 disabled:opacity-50"
      >
        <Trash2 className="h-3.5 w-3.5" />
        {isDeleting ? 'Deleting...' : `Delete ${selectedCount}`}
      </button>
    </div>
  );
};
