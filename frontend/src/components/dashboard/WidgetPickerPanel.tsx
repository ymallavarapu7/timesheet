import React, { useEffect, useRef, useState } from 'react';
import { X, Clock, BarChart3, Palmtree } from 'lucide-react';
import gsap from 'gsap';
import { WIDGET_REGISTRY, type WidgetKey, type WidgetVisibility } from '@/hooks/useWidgetPreferences';

interface WidgetPickerPanelProps {
  isOpen: boolean;
  onClose: () => void;
  state: WidgetVisibility;
  onToggle: (key: WidgetKey) => void;
}

const GROUP_META: Record<string, { label: string; icon: React.ReactNode }> = {
  overview: { label: 'Overview', icon: <Clock className="h-4 w-4" /> },
  projects: { label: 'Projects & Activities', icon: <BarChart3 className="h-4 w-4" /> },
  leave: { label: 'Leave & Attendance', icon: <Palmtree className="h-4 w-4" /> },
};

export const WidgetPickerPanel: React.FC<WidgetPickerPanelProps> = ({ isOpen, onClose, state, onToggle }) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  const [isMobile, setIsMobile] = useState(typeof window !== 'undefined' ? window.innerWidth < 768 : false);

  useEffect(() => {
    const handler = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  useEffect(() => {
    if (isOpen) {
      if (backdropRef.current) {
        gsap.fromTo(backdropRef.current, { opacity: 0 }, { opacity: 1, duration: 0.25 });
      }
      if (panelRef.current) {
        if (isMobile) {
          gsap.fromTo(panelRef.current, { y: '100%' }, { y: '0%', duration: 0.35, ease: 'power3.out' });
        } else {
          gsap.fromTo(panelRef.current, { x: '100%' }, { x: '0%', duration: 0.35, ease: 'power3.out' });
        }
      }
    }
  }, [isOpen, isMobile]);

  const handleClose = () => {
    const tl = gsap.timeline({ onComplete: onClose });
    if (panelRef.current) {
      if (isMobile) {
        tl.to(panelRef.current, { y: '100%', duration: 0.25, ease: 'power2.in' }, 0);
      } else {
        tl.to(panelRef.current, { x: '100%', duration: 0.25, ease: 'power2.in' }, 0);
      }
    }
    if (backdropRef.current) {
      tl.to(backdropRef.current, { opacity: 0, duration: 0.2 }, 0.05);
    }
  };

  if (!isOpen) return null;

  const groups: Record<string, typeof WIDGET_REGISTRY> = {};
  for (const w of WIDGET_REGISTRY) {
    if (!groups[w.group]) groups[w.group] = [];
    groups[w.group].push(w);
  }

  const panelContent = (
    <>
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card px-5 py-4">
        <h2 className="text-base font-semibold text-foreground">Customize Widgets</h2>
        <button
          type="button"
          onClick={handleClose}
          className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
          aria-label="Close picker"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="p-5 space-y-6">
        {Object.entries(groups).map(([groupKey, widgets]) => {
          const meta = GROUP_META[groupKey] ?? { label: groupKey, icon: null };
          return (
            <div key={groupKey}>
              <div className="flex items-center gap-2 mb-3">
                <span className="text-muted-foreground">{meta.icon}</span>
                <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                  {meta.label}
                </h3>
              </div>
              <div className="space-y-1">
                {widgets.map((w) => (
                  <button
                    key={w.key}
                    type="button"
                    onClick={() => onToggle(w.key)}
                    className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition hover:bg-muted/50"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground">{w.label}</p>
                      <p className="text-xs text-muted-foreground truncate">{w.description}</p>
                    </div>
                    <div
                      className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
                        state[w.key] ? 'bg-primary' : 'bg-muted'
                      }`}
                    >
                      <div
                        className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
                          state[w.key] ? 'translate-x-4' : 'translate-x-0.5'
                        }`}
                      />
                    </div>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );

  return (
    <div className="fixed inset-0 z-50">
      <div
        ref={backdropRef}
        className="absolute inset-0 bg-black/40"
        onClick={handleClose}
      />

      {isMobile ? (
        <div
          ref={panelRef}
          className="absolute inset-x-0 bottom-0 max-h-[75vh] overflow-y-auto rounded-t-2xl border-t border-border bg-card shadow-2xl"
          style={{ transform: 'translateY(100%)' }}
        >
          <div className="sticky top-0 z-10 bg-card pt-2 pb-0">
            <div className="mx-auto mb-2 h-1 w-10 rounded-full bg-muted-foreground/30" />
          </div>
          {panelContent}
        </div>
      ) : (
        <div
          ref={panelRef}
          className="absolute right-0 top-0 h-full w-[360px] overflow-y-auto border-l border-border bg-card shadow-2xl"
          style={{ transform: 'translateX(100%)' }}
        >
          {panelContent}
        </div>
      )}
    </div>
  );
};
