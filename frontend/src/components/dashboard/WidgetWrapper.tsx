import React from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, Maximize2 } from 'lucide-react';
import type { WidgetKey } from '@/hooks/useWidgetPreferences';
import { ALLOWED_SIZES } from '@/hooks/useDashboardPrefs';

interface WidgetWrapperProps {
  id: WidgetKey;
  span: number;
  title?: string;
  onResize?: () => void;
  children: React.ReactNode;
  isMobile?: boolean;
}

export const WidgetWrapper: React.FC<WidgetWrapperProps> = ({
  id,
  span,
  title,
  onResize,
  children,
  isMobile = false,
}) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    gridColumn: isMobile ? '1 / -1' : `span ${span}`,
  };

  const allowedSizes = ALLOWED_SIZES[id];
  const canResize = allowedSizes && allowedSizes.length > 1 && !isMobile;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`group/slot relative ${isDragging ? 'z-50 opacity-40 scale-[1.02]' : ''}`}
    >
      <button
        type="button"
        className="absolute top-3 left-3 z-20 flex h-6 w-6 items-center justify-center rounded-full bg-muted/80 text-muted-foreground opacity-0 transition-all duration-200 hover:bg-primary/20 hover:text-primary group-hover/slot:opacity-100 cursor-grab active:cursor-grabbing"
        aria-label={`Drag ${title ?? 'widget'}`}
        {...attributes}
        {...listeners}
      >
        <GripVertical className="h-3.5 w-3.5" />
      </button>

      {canResize && onResize && (
        <button
          type="button"
          onClick={onResize}
          className="absolute bottom-3 right-3 z-20 flex h-[18px] w-[18px] items-center justify-center rounded-sm bg-muted/80 text-muted-foreground opacity-0 transition-all duration-200 hover:bg-primary/20 hover:text-primary group-hover/slot:opacity-100"
          aria-label={`Resize ${title ?? 'widget'}`}
          title={`Current: ${span} cols. Click to cycle.`}
        >
          <Maximize2 className="h-3 w-3" style={{ transform: 'rotate(135deg)' }} />
        </button>
      )}

      {isDragging && (
        <div className="absolute inset-0 rounded-2xl border-2 border-[#00d4aa] pointer-events-none z-10" />
      )}

      {children}
    </div>
  );
};
