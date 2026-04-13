import React from 'react';
import { useTheme } from '@/contexts/ThemeContext';

interface AcufyLogoProps {
  /** 'full' = icon + wordmark, 'icon' = icon only */
  variant?: 'full' | 'icon';
  className?: string;
}

/** Neural Prism icon (shared between both variants) */
const NeuralPrismIcon: React.FC<{ size?: number }> = ({ size = 36 }) => (
  <svg width={size} height={size} viewBox="-5 -5 170 130" xmlns="http://www.w3.org/2000/svg">
    <g transform="translate(60,65)">
      <path d="M0 -55 L50 -27 L50 27 L0 55 L-50 27 L-50 -27 Z" fill="none" stroke="#0EA5E9" strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M0 -36 L35 16 L-35 16 Z" fill="#0EA5E9" fillOpacity="0.15" />
      <path d="M0 -36 L35 16 L-35 16 Z" fill="none" stroke="#14B8A6" strokeWidth="1.8" strokeLinejoin="round" />
      <line x1="0" y1="-2" x2="0" y2="-36" stroke="#0EA5E9" strokeWidth="1" opacity="0.5" />
      <line x1="0" y1="-2" x2="35" y2="16" stroke="#14B8A6" strokeWidth="1" opacity="0.5" />
      <line x1="0" y1="-2" x2="-35" y2="16" stroke="#06B6D4" strokeWidth="1" opacity="0.5" />
      <circle cx="0" cy="-2" r="6" fill="#0EA5E9" />
      <circle cx="0" cy="-55" r="4.5" fill="#0EA5E9" />
      <circle cx="50" cy="-27" r="4" fill="#06B6D4" />
      <circle cx="50" cy="27" r="4" fill="#14B8A6" />
      <circle cx="0" cy="55" r="4" fill="#2DD4BF" />
      <circle cx="-50" cy="27" r="4" fill="#10B981" />
      <circle cx="-50" cy="-27" r="4" fill="#0EA5E9" />
      {/* Sparkle dust — dots */}
      <circle cx="62" cy="-48" r="3.5" fill="#0EA5E9" opacity="0.9" />
      <circle cx="78" cy="-34" r="2.5" fill="#14B8A6" opacity="0.75" />
      <circle cx="85" cy="-50" r="2" fill="#2DD4BF" opacity="0.8" />
      {/* Sparkle dust — four-point stars */}
      <path d="M72 -52 L74.5 -60 L77 -52 L85 -49.5 L77 -47 L74.5 -39 L72 -47 L64 -49.5 Z" fill="#0EA5E9" opacity="0.75" />
      <path d="M88 -28 L90 -33 L92 -28 L97 -26 L92 -24 L90 -19 L88 -24 L83 -26 Z" fill="#2DD4BF" opacity="0.6" />
    </g>
  </svg>
);

export const AcufyLogo: React.FC<AcufyLogoProps> = ({ variant = 'full', className }) => {
  const { theme } = useTheme();
  const textFill = theme === 'dark' ? '#F1F5F9' : '#0F172A';
  const taglineFill = theme === 'dark' ? '#94A3B8' : '#64748B';

  if (variant === 'icon') {
    return (
      <span className={className}>
        <NeuralPrismIcon size={48} />
      </span>
    );
  }

  return (
    <span className={`inline-flex items-center gap-2.5 ${className ?? ''}`}>
      <NeuralPrismIcon size={48} />
      <span className="flex flex-col">
        <span className="flex items-baseline gap-1">
          <svg width="90" height="22" viewBox="0 0 160 36" xmlns="http://www.w3.org/2000/svg">
            <text x="0" y="26" fontFamily="'Plus Jakarta Sans','SF Pro Display','Segoe UI',system-ui,sans-serif" fontSize="28" fontWeight="700" letterSpacing="2.5" fill={textFill}>ACUFY</text>
            <text x="118" y="26" fontFamily="'Plus Jakarta Sans','SF Pro Display','Segoe UI',system-ui,sans-serif" fontSize="18" fontWeight="500" letterSpacing="1.5" fill="#2DD4BF">AI</text>
          </svg>
        </span>
        <span style={{ color: taglineFill }} className="mt-[-2px] text-[9px] font-medium uppercase tracking-[2.5px]">
          AI Powered Innovation
        </span>
      </span>
    </span>
  );
};

export { NeuralPrismIcon };
