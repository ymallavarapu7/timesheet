import React, { useEffect, useRef, useState } from 'react';
import { Check, Palette } from 'lucide-react';
import { useTheme } from '@/contexts/ThemeContext';
import { THEME_VARIANTS } from '@/contexts/themeVariants';
import { cn } from '@/lib/utils';

/**
 * Theme picker dropdown — opens on click, shows all 8 variants
 * with a preview swatch + logo thumbnail. Clicking a variant applies it.
 */
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
        <div className="absolute right-0 top-11 z-50 w-[380px] rounded-2xl border border-border bg-card p-2 shadow-[0_18px_40px_rgba(0,0,0,0.15)]">
          <div className="px-3 py-2">
            <p className="text-sm font-semibold text-foreground">Theme</p>
            <p className="text-xs text-muted-foreground">Pick a color scheme and logo.</p>
          </div>
          <div className="max-h-[420px] overflow-y-auto p-1">
            {variants.map((key) => {
              const v = THEME_VARIANTS[key];
              const active = key === variantKey;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => { setVariant(key); setOpen(false); }}
                  className={cn(
                    'flex w-full items-center gap-3 rounded-xl p-2 text-left transition',
                    active ? 'bg-primary/10' : 'hover:bg-muted/50',
                  )}
                >
                  <div className="min-w-0 flex-1 flex items-center gap-3">
                    <div
                      className="flex-shrink-0 h-9 w-32 rounded-md overflow-hidden flex items-center justify-center"
                      style={{ backgroundColor: v.legacy.bgApp }}
                    >
                      <img
                        src={v.logoPath}
                        alt=""
                        style={{ width: '100%', height: 'auto', display: 'block' }}
                      />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-foreground">{v.label}</p>
                      <p className="text-xs text-muted-foreground capitalize">{v.mode}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span
                      className="h-4 w-4 rounded-full border border-border/60"
                      style={{ backgroundColor: v.legacy.accentBlue }}
                    />
                    {active && <Check className="h-4 w-4 text-primary" />}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
