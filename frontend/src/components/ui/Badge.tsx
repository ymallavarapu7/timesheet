import React from 'react';

import { cn } from '@/lib/utils';

type BadgeTone = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'outline';

const toneClasses: Record<BadgeTone, string> = {
  default: 'bg-[var(--bg-surface-3)] text-[var(--text-secondary)]',
  success: 'bg-[var(--success-light)] text-[var(--success)]',
  warning: 'bg-[var(--warning-light)] text-[var(--warning)]',
  danger: 'bg-[var(--danger-light)] text-[var(--danger)]',
  info: 'bg-[var(--info-light)] text-[var(--info)]',
  outline: 'bg-[var(--bg-surface-2)] text-[var(--text-secondary)]',
};

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

export const Badge: React.FC<BadgeProps> = ({ className, tone = 'default', ...props }) => (
  <span
    className={cn(
      'inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium',
      toneClasses[tone],
      className,
    )}
    {...props}
  />
);
