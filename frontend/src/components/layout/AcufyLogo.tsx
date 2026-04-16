import React from 'react';
import { useTheme } from '@/contexts/ThemeContext';

interface AcufyLogoProps {
  /** 'full' = logo + wordmark (as rendered in the PNG), 'icon' = logo only (clipped). */
  variant?: 'full' | 'icon';
  className?: string;
}

/**
 * Renders the current theme variant's logo PNG.
 * The source PNGs have a baked-in dark background. We use mix-blend-mode
 * so that dark pixels disappear against the page background, leaving only
 * the bright logo strokes visible — this integrates the logo cleanly on
 * any page background without showing a visible box around it.
 */
export const AcufyLogo: React.FC<AcufyLogoProps> = ({ variant = 'full', className }) => {
  const { variant: themeVariant } = useTheme();
  const src = themeVariant.logoPath;

  if (variant === 'icon') {
    return (
      <span
        className={`inline-block overflow-hidden ${className ?? ''}`}
        style={{ width: 40, height: 40 }}
      >
        <img src={src} alt="Acufy AI" style={{ height: '100%', width: 'auto', maxWidth: 'none' }} />
      </span>
    );
  }

  return (
    <img src={src} alt="Acufy AI" className={className} style={{ height: 44, width: 'auto' }} />
  );
};

/** Kept as an alias so existing imports don't break. */
export const NeuralPrismIcon: React.FC<{ size?: number }> = ({ size = 40 }) => {
  const { variant } = useTheme();
  return (
    <span className="inline-block overflow-hidden" style={{ width: size, height: size }}>
      <img
        src={variant.logoPath}
        alt="Acufy AI"
        style={{ height: '100%', width: 'auto', maxWidth: 'none' }}
      />
    </span>
  );
};
