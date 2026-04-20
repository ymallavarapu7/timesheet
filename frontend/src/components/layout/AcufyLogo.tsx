import React from 'react';
import { useTheme } from '@/contexts/ThemeContext';

interface AcufyLogoProps {
  /** 'full' = logo + wordmark (as rendered in the PNG), 'icon' = logo only (clipped). */
  variant?: 'full' | 'icon';
  className?: string;
  /** Explicit display height in px for the full variant. Default 56. */
  height?: number;
}

/**
 * Renders the current theme variant's logo PNG.
 * Source PNGs are 1350x288 (≈4.69:1). We render at a generous display
 * height so the baked-in tagline stays readable on hi-DPI screens, and use
 * image-rendering hints so the browser resamples cleanly.
 */
export const AcufyLogo: React.FC<AcufyLogoProps> = ({ variant = 'full', className, height = 56 }) => {
  const { variant: themeVariant } = useTheme();
  const src = themeVariant.logoPath;

  const commonImgStyle: React.CSSProperties = {
    imageRendering: 'auto',
  };

  if (variant === 'icon') {
    const iconSize = Math.round(height * 0.85);
    return (
      <span
        className={`inline-block overflow-hidden ${className ?? ''}`}
        style={{ width: iconSize, height: iconSize }}
      >
        <img
          src={src}
          alt="Acufy AI"
          decoding="async"
          style={{ ...commonImgStyle, height: '100%', width: 'auto', maxWidth: 'none' }}
        />
      </span>
    );
  }

  return (
    <img
      src={src}
      alt="Acufy AI"
      decoding="async"
      className={className}
      style={{ ...commonImgStyle, height, width: 'auto' }}
    />
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
        decoding="async"
        style={{ imageRendering: 'auto', height: '100%', width: 'auto', maxWidth: 'none' }}
      />
    </span>
  );
};
