/**
 * Theme variant definitions.
 * slate-bg and white-bg are the default dark and light themes.
 * The other 6 variants share the same dark slate background — they differ
 * only in primary/accent color and the logo.
 */

export type ThemeVariantKey =
  | 'slate-bg'
  | 'white-bg'
  | 'original'
  | 'emerald'
  | 'amber-red'
  | 'purple'
  | 'rose'
  | 'royal-blue';

export type ThemeMode = 'dark' | 'light';

export interface ThemeVariant {
  key: ThemeVariantKey;
  label: string;
  mode: ThemeMode;
  logoPath: string;
  tokens: {
    background: string;
    foreground: string;
    card: string;
    cardForeground: string;
    primary: string;
    primaryForeground: string;
    secondary: string;
    secondaryForeground: string;
    muted: string;
    mutedForeground: string;
    accent: string;
    accentForeground: string;
    border: string;
    input: string;
    ring: string;
    popover: string;
    popoverForeground: string;
  };
  legacy: {
    accentBlue: string;
    accentLight: string;
    accentHover: string;
    bgApp: string;
    bgSurface: string;
    bgSurface2: string;
    textPrimary: string;
    textSecondary: string;
    glassBg: string;
    glassBorder: string;
  };
}

// Prefix with the Vite base path so logo URLs resolve correctly when the app
// is deployed under a sub-path (e.g. /app/timesheet). import.meta.env.BASE_URL
// *usually* ends with a trailing slash but don't assume it — normalize explicitly.
const LOGO_BASE = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/logos`;

// ── Shared neutral dark base ───────────────────────────────────
// Near-black neutral surfaces — no hue tint — so any accent color
// (orange, purple, emerald, etc.) reads correctly against it.
const neutralDarkBase = {
  background: '0 0% 6%',       // ~#0F0F0F
  foreground: '0 0% 95%',
  card: '0 0% 9%',             // ~#171717
  cardForeground: '0 0% 95%',
  secondary: '0 0% 14%',
  secondaryForeground: '0 0% 95%',
  muted: '0 0% 14%',
  mutedForeground: '0 0% 60%',
  border: '0 0% 18%',
  input: '0 0% 18%',
  popover: '0 0% 9%',
  popoverForeground: '0 0% 95%',
};

const neutralDarkLegacy = {
  bgApp: '#0F0F0F',
  bgSurface: '#171717',
  bgSurface2: '#242424',
  textPrimary: '#F2F2F2',
  textSecondary: '#999999',
};

// ── Original blue-tinted slate (kept for slate-bg variant only) ──
const slateDarkBase = {
  background: '222 47% 9%',
  foreground: '213 31% 96%',
  card: '217 48% 11%',
  cardForeground: '213 31% 96%',
  secondary: '217 33% 17%',
  secondaryForeground: '213 31% 96%',
  muted: '217 33% 17%',
  mutedForeground: '215 20% 65%',
  border: '217 28% 22%',
  input: '217 28% 22%',
  popover: '217 48% 11%',
  popoverForeground: '213 31% 96%',
};

const slateDarkLegacy = {
  bgApp: '#0B1120',
  bgSurface: '#0F172A',
  bgSurface2: '#1E293B',
  textPrimary: '#F1F5F9',
  textSecondary: '#94A3B8',
};

// Helper: compose a dark variant with the given accent color.
// By default uses the neutral near-black background; pass useSlateBase=true
// to keep the blue-tinted slate base (only slate-bg variant uses it).
const darkVariant = (args: {
  key: ThemeVariantKey;
  label: string;
  logoFile: string;
  accent: string;          // HSL e.g. "199 89% 48%"
  accentHex: string;       // e.g. "#0EA5E9"
  accentHoverHex: string;  // e.g. "#38BDF8"
  accentLightRgba: string; // e.g. "rgba(14, 165, 233, 0.12)"
  glassBorderRgba: string; // e.g. "rgba(14, 165, 233, 0.1)"
  useSlateBase?: boolean;
}): ThemeVariant => {
  const base = args.useSlateBase ? slateDarkBase : neutralDarkBase;
  const legacy = args.useSlateBase ? slateDarkLegacy : neutralDarkLegacy;
  const glassBg = args.useSlateBase ? 'rgba(11, 17, 32, 0.85)' : 'rgba(15, 15, 15, 0.85)';
  return {
    key: args.key,
    label: args.label,
    mode: 'dark',
    logoPath: `${LOGO_BASE}/${args.logoFile}`,
    tokens: {
      ...base,
      primary: args.accent,
      primaryForeground: '0 0% 100%',
      accent: args.accent,
      accentForeground: '0 0% 100%',
      ring: args.accent,
    },
    legacy: {
      ...legacy,
      accentBlue: args.accentHex,
      accentLight: args.accentLightRgba,
      accentHover: args.accentHoverHex,
      glassBg,
      glassBorder: args.glassBorderRgba,
    },
  };
};

// ── Variants ──────────────────────────────────────────────────

const slateBg: ThemeVariant = darkVariant({
  key: 'slate-bg',
  label: 'Slate (dark)',
  logoFile: 'acufy-color-slate-bg.png',
  accent: '199 89% 48%',
  accentHex: '#0EA5E9',
  accentHoverHex: '#38BDF8',
  accentLightRgba: 'rgba(14, 165, 233, 0.12)',
  glassBorderRgba: 'rgba(14, 165, 233, 0.1)',
  useSlateBase: true,
});

const whiteBg: ThemeVariant = {
  key: 'white-bg',
  label: 'Light',
  mode: 'light',
  logoPath: `${LOGO_BASE}/acufy-color-white-bg.png`,
  tokens: {
    background: '216 33% 97%',
    foreground: '222 22% 8%',
    card: '0 0% 100%',
    cardForeground: '222 22% 8%',
    primary: '199 89% 48%',
    primaryForeground: '0 0% 100%',
    secondary: '220 24% 92%',
    secondaryForeground: '222 22% 8%',
    muted: '220 24% 94%',
    mutedForeground: '220 14% 44%',
    accent: '199 89% 48%',
    accentForeground: '0 0% 100%',
    border: '214 32% 91%',
    input: '214 32% 91%',
    ring: '199 89% 48%',
    popover: '0 0% 100%',
    popoverForeground: '222 22% 8%',
  },
  legacy: {
    accentBlue: '#0EA5E9',
    accentLight: '#f0f9ff',
    accentHover: '#0284C7',
    bgApp: '#f5f7fa',
    bgSurface: '#ffffff',
    bgSurface2: '#f0f2f5',
    textPrimary: '#0f1117',
    textSecondary: '#5c6474',
    glassBg: 'rgba(255, 255, 255, 0.85)',
    glassBorder: 'rgba(14, 165, 233, 0.08)',
  },
};

const original = darkVariant({
  key: 'original',
  label: 'Teal',
  logoFile: 'acufy-color-original.png',
  accent: '168 76% 42%',
  accentHex: '#14B8A6',
  accentHoverHex: '#2DD4BF',
  accentLightRgba: 'rgba(20, 184, 166, 0.12)',
  glassBorderRgba: 'rgba(20, 184, 166, 0.12)',
});

const emerald = darkVariant({
  key: 'emerald',
  label: 'Emerald',
  logoFile: 'acufy-color-emerald.png',
  accent: '142 71% 45%',
  accentHex: '#22c55e',
  accentHoverHex: '#4ade80',
  accentLightRgba: 'rgba(34, 197, 94, 0.12)',
  glassBorderRgba: 'rgba(34, 197, 94, 0.14)',
});

const amberRed = darkVariant({
  key: 'amber-red',
  label: 'Amber',
  logoFile: 'acufy-color-amber-red.png',
  accent: '24 95% 53%',
  accentHex: '#f97316',
  accentHoverHex: '#fb923c',
  accentLightRgba: 'rgba(249, 115, 22, 0.12)',
  glassBorderRgba: 'rgba(249, 115, 22, 0.14)',
});

const purple = darkVariant({
  key: 'purple',
  label: 'Purple',
  logoFile: 'acufy-color-purple.png',
  accent: '270 76% 62%',
  accentHex: '#a855f7',
  accentHoverHex: '#c084fc',
  accentLightRgba: 'rgba(168, 85, 247, 0.12)',
  glassBorderRgba: 'rgba(168, 85, 247, 0.14)',
});

const rose = darkVariant({
  key: 'rose',
  label: 'Rose',
  logoFile: 'acufy-color-rose.png',
  accent: '346 77% 60%',
  accentHex: '#f43f5e',
  accentHoverHex: '#fb7185',
  accentLightRgba: 'rgba(244, 63, 94, 0.12)',
  glassBorderRgba: 'rgba(244, 63, 94, 0.14)',
});

const royalBlue = darkVariant({
  key: 'royal-blue',
  label: 'Royal blue',
  logoFile: 'acufy-color-royal-blue.png',
  accent: '225 83% 60%',
  accentHex: '#4f46e5',
  accentHoverHex: '#6366f1',
  accentLightRgba: 'rgba(79, 70, 229, 0.14)',
  glassBorderRgba: 'rgba(79, 70, 229, 0.16)',
});

export const THEME_VARIANTS: Record<ThemeVariantKey, ThemeVariant> = {
  'slate-bg': slateBg,
  'white-bg': whiteBg,
  'original': original,
  'emerald': emerald,
  'amber-red': amberRed,
  'purple': purple,
  'rose': rose,
  'royal-blue': royalBlue,
};

export const THEME_VARIANT_ORDER: ThemeVariantKey[] = [
  'slate-bg',
  'white-bg',
  'original',
  'emerald',
  'amber-red',
  'purple',
  'rose',
  'royal-blue',
];

export function applyThemeVariant(variant: ThemeVariant) {
  const root = document.documentElement;
  root.classList.remove('light', 'dark');
  root.classList.add(variant.mode);

  const t = variant.tokens;
  root.style.setProperty('--background', t.background);
  root.style.setProperty('--foreground', t.foreground);
  root.style.setProperty('--card', t.card);
  root.style.setProperty('--card-foreground', t.cardForeground);
  root.style.setProperty('--primary', t.primary);
  root.style.setProperty('--primary-foreground', t.primaryForeground);
  root.style.setProperty('--secondary', t.secondary);
  root.style.setProperty('--secondary-foreground', t.secondaryForeground);
  root.style.setProperty('--muted', t.muted);
  root.style.setProperty('--muted-foreground', t.mutedForeground);
  root.style.setProperty('--accent', t.accent);
  root.style.setProperty('--accent-foreground', t.accentForeground);
  root.style.setProperty('--border', t.border);
  root.style.setProperty('--input', t.input);
  root.style.setProperty('--ring', t.ring);
  root.style.setProperty('--popover', t.popover);
  root.style.setProperty('--popover-foreground', t.popoverForeground);

  const l = variant.legacy;
  root.style.setProperty('--accent-blue', l.accentBlue);
  root.style.setProperty('--accent-light', l.accentLight);
  root.style.setProperty('--accent-hover', l.accentHover);
  root.style.setProperty('--bg-app', l.bgApp);
  root.style.setProperty('--bg-surface', l.bgSurface);
  root.style.setProperty('--bg-surface-2', l.bgSurface2);
  root.style.setProperty('--text-primary', l.textPrimary);
  root.style.setProperty('--text-secondary', l.textSecondary);
  root.style.setProperty('--glass-bg', l.glassBg);
  root.style.setProperty('--glass-border', l.glassBorder);

  const metaThemeColor = document.querySelector('meta[name="theme-color"]');
  if (metaThemeColor) metaThemeColor.setAttribute('content', l.bgApp);
}
