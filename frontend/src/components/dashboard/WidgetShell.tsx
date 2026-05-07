import React, { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import gsap from 'gsap';

interface WidgetShellProps {
  widgetKey: string;
  span: number;
  title?: React.ReactNode;
  onRemove?: () => void;
  children: React.ReactNode;
  className?: string;
}

export const WidgetShell: React.FC<WidgetShellProps> = ({
  widgetKey,
  span,
  title,
  onRemove,
  children,
  className = '',
}) => {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    gsap.fromTo(
      ref.current,
      { opacity: 0, y: 18, scale: 0.97 },
      { opacity: 1, y: 0, scale: 1, duration: 0.45, ease: 'power2.out' },
    );
  }, []);

  return (
    <div
      ref={ref}
      data-widget={widgetKey}
      className={`group relative overflow-hidden rounded-2xl border border-border/40 bg-card/40 p-6 backdrop-blur-2xl transition-all duration-500 hover:border-border/80 hover:bg-card/60 hover:shadow-2xl hover:shadow-primary/5 hover:ring-1 hover:ring-primary/10 flex flex-col h-full ${className}`}
      style={{
        gridColumn: `span ${span}`,
      }}
    >
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="absolute top-3 right-3 z-10 flex h-6 w-6 items-center justify-center rounded-full bg-muted/80 text-muted-foreground opacity-0 transition-all duration-200 hover:bg-destructive/20 hover:text-destructive group-hover:opacity-100"
          aria-label={`Remove ${title ?? 'widget'}`}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}

      {title && (
        <p className="mb-3 text-[11px] font-bold uppercase tracking-widest text-muted-foreground/70 shrink-0">
          {title}
        </p>
      )}

      <div className="flex-1 flex flex-col relative z-10">
        {children}
      </div>
    </div>
  );
};
