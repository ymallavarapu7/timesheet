import React from 'react';

import { cn } from '@/lib/utils';

export const LoadingSkeleton: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, ...props }) => (
  <div
    className={cn('animate-pulse rounded-lg bg-[linear-gradient(90deg,#f0f2f5,#e8ebf0,#f0f2f5)] bg-[length:200%_100%]', className)}
    {...props}
  />
);
