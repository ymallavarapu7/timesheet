import React from 'react';
import { Loader2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';

interface LoadingProps {
  message?: string;
}

export const Loading: React.FC<LoadingProps> = ({ message = 'Loading...' }) => (
  <div className="flex min-h-[40vh] items-center justify-center">
    <Card className="max-w-md">
      <CardContent className="py-10 text-center">
        <Loader2 className="mx-auto mb-3 h-8 w-8 animate-spin text-amber-200" />
        <p className="text-sm text-muted-foreground">{message}</p>
      </CardContent>
    </Card>
  </div>
);

interface ErrorProps {
  title?: string;
  message: string;
  action?: () => void;
  actionLabel?: string;
}

export const Error: React.FC<ErrorProps> = ({ 
  title = 'Error', 
  message, 
  action, 
  actionLabel = 'Try Again' 
}) => (
  <div className="flex min-h-[40vh] items-center justify-center">
    <div className="max-w-md rounded-3xl border border-rose-400/20 bg-rose-400/8 px-8 py-8 text-center">
      <h1 className="mb-2 text-2xl font-bold">{title}</h1>
      <p className="mb-4 text-muted-foreground">{message}</p>
      {action && (
        <button
          onClick={action}
          className="rounded-full border border-border/70 bg-white/5 px-4 py-2 text-sm font-medium text-foreground transition hover:border-amber-300/40"
        >
          {actionLabel}
        </button>
      )}
    </div>
  </div>
);

export const EmptyState: React.FC<{ message: string }> = ({ message }) => (
  <div className="flex items-center justify-center rounded-3xl border border-dashed border-border/70 bg-card/60 px-6 py-12">
    <p className="text-sm text-muted-foreground">{message}</p>
  </div>
);
