import React, { useEffect, useRef, useState } from 'react';
import { Check, Palette } from 'lucide-react';
import { useTheme } from '@/contexts/ThemeContext';
import { THEME_VARIANTS } from '@/contexts/themeVariants';
import { cn } from '@/lib/utils';

// Theme picker dropdown showing logo thumbnails in a 4-per-row grid.
export const ThemePicker: React.FC = () => {
  const { variantKey, setVariant, variants } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground"
        aria-label="Change theme"
        title="Change theme"
      >
        <Palette className="h-4 w-4" />
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-50 w-[640px] max-w-[calc(100vw-2rem)] rounded-2xl border border-border bg-card p-4 shadow-[0_18px_40px_rgba(0,0,0,0.15)]">
          <div className="grid grid-cols-4 gap-3">
            {variants.map((key) => {
              const v = THEME_VARIANTS[key];
              const active = key === variantKey;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => { setVariant(key); setOpen(false); }}
                  className={cn(
                    'flex flex-col items-center gap-2 rounded-lg p-2 text-center transition',
                    active ? 'bg-primary/10 ring-1 ring-primary/40' : 'hover:bg-muted/50',
                  )}
                  title={v.label}
                  aria-label={`Apply ${v.label} theme`}
                  aria-pressed={active}
                >
                  <div
                    className="relative h-20 w-full rounded-md overflow-hidden"
                    style={{ backgroundColor: v.legacy.bgApp }}
                  >
                    <img
                      src={v.logoPath}
                      alt=""
                      className="absolute inset-0 m-auto"
                      style={{
                        maxHeight: '100%',
                        maxWidth: '100%',
                        width: 'auto',
                        height: 'auto',
                        objectFit: 'contain',
                        display: 'block',
                      }}
                    />
                    {active && (
                      <span
                        className="absolute right-1 top-1 inline-flex h-4 w-4 items-center justify-center rounded-full bg-primary text-primary-foreground shadow"
                        aria-hidden
                      >
                        <Check className="h-3 w-3" strokeWidth={3} />
                      </span>
                    )}
                  </div>
                  <span className="block text-xs font-medium leading-tight text-foreground truncate w-full">
                    {v.label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
