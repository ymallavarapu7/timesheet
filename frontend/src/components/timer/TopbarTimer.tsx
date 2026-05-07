import React from 'react';
import { Play, Square, Pause, Timer } from 'lucide-react';
import { useTimer } from '@/hooks/useTimer';
import { cn } from '@/lib/utils';

export function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;

  const mStr = m.toString().padStart(2, '0');
  const sStr = s.toString().padStart(2, '0');

  if (h > 0) {
    return `${h}:${mStr}:${sStr}`;
  }
  return `${mStr}:${sStr}`;
}

export const TopbarTimer: React.FC = () => {
  const { status, elapsedMs, start, pause, resume, stop } = useTimer();

  if (status === 'idle' || status === 'stopped') {
    return (
      <button
        onClick={start}
        title="Start live timer"
        className="flex items-center justify-center rounded-lg border border-border bg-transparent h-8 w-8 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <Timer className="h-4 w-4" />
      </button>
    );
  }

  if (status === 'running') {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-[#00D4AA]/40 bg-[#00D4AA]/10 px-3 py-1.5 transition-all">
        <div className="font-mono text-sm font-bold text-[#00D4AA] animate-pulse">
          {formatElapsed(elapsedMs)}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={pause} className="text-[#00D4AA] hover:opacity-80 p-0.5" title="Pause">
            <Pause className="h-4 w-4 fill-current" />
          </button>
          <button onClick={stop} className="text-destructive hover:opacity-80 p-0.5" title="Stop">
            <Square className="h-4 w-4 fill-current" />
          </button>
        </div>
      </div>
    );
  }

  // paused state
  return (
    <div className="flex items-center gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 transition-all">
      <div className="font-mono text-sm font-bold text-amber-500 opacity-80">
        {formatElapsed(elapsedMs)}
      </div>
      <div className="flex items-center gap-1">
        <button onClick={resume} className="text-amber-500 hover:opacity-80 p-0.5" title="Resume">
          <Play className="h-4 w-4 fill-current" />
        </button>
        <button onClick={stop} className="text-destructive hover:opacity-80 p-0.5" title="Stop">
          <Square className="h-4 w-4 fill-current" />
        </button>
      </div>
    </div>
  );
};
