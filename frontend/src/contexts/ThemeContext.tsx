import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import {
  THEME_VARIANTS,
  THEME_VARIANT_ORDER,
  applyThemeVariant,
  type ThemeVariantKey,
  type ThemeMode,
} from './themeVariants';

interface ThemeContextValue {
  variantKey: ThemeVariantKey;
  variant: ReturnType<typeof currentVariant>;
  setVariant: (key: ThemeVariantKey) => void;
  variants: typeof THEME_VARIANT_ORDER;
  // Backwards-compat with the old API
  theme: ThemeMode;
  toggleTheme: () => void;
  setTheme: (mode: ThemeMode) => void;
}

function currentVariant(key: ThemeVariantKey) {
  return THEME_VARIANTS[key];
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

const STORAGE_KEY = 'acufy-theme-variant';
const LEGACY_STORAGE_KEY = 'acufy-theme';

function getInitialVariant(): ThemeVariantKey {
  const stored = localStorage.getItem(STORAGE_KEY) as ThemeVariantKey | null;
  if (stored && stored in THEME_VARIANTS) return stored;
  // Legacy fallback: map old light/dark preference to white-bg/slate-bg
  const legacy = localStorage.getItem(LEGACY_STORAGE_KEY);
  if (legacy === 'light') return 'white-bg';
  if (legacy === 'dark') return 'slate-bg';
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  return prefersDark ? 'slate-bg' : 'white-bg';
}

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [variantKey, setVariantKey] = useState<ThemeVariantKey>(getInitialVariant);

  useEffect(() => {
    applyThemeVariant(THEME_VARIANTS[variantKey]);
  }, [variantKey]);

  const setVariant = useCallback((key: ThemeVariantKey) => {
    localStorage.setItem(STORAGE_KEY, key);
    setVariantKey(key);
  }, []);

  // Backwards-compat API for any code still calling theme toggle
  const theme: ThemeMode = THEME_VARIANTS[variantKey].mode;
  const setTheme = useCallback((mode: ThemeMode) => {
    setVariant(mode === 'dark' ? 'slate-bg' : 'white-bg');
  }, [setVariant]);
  const toggleTheme = useCallback(() => {
    setTheme(theme === 'dark' ? 'light' : 'dark');
  }, [theme, setTheme]);

  return (
    <ThemeContext.Provider
      value={{
        variantKey,
        variant: THEME_VARIANTS[variantKey],
        setVariant,
        variants: THEME_VARIANT_ORDER,
        theme,
        toggleTheme,
        setTheme,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = (): ThemeContextValue => {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
};
