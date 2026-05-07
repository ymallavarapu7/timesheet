import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { GripHorizontal, Minus, X, Pause, Play, Square } from 'lucide-react';
import { useTimer } from '@/hooks/useTimer';
import { formatElapsed } from './TopbarTimer';
import { cn } from '@/lib/utils';
import { useProjects, useTasks } from '@/hooks/useData';

export const FloatingTimer: React.FC = () => {
  const { status, elapsedMs, projectId, taskId, pause, resume, stop, discard } = useTimer();
  const [minimized, setMinimized] = useState(false);

  const [pos, setPos] = useState({ x: window.innerWidth - 250, y: window.innerHeight - 150 });
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<{ startX: number, startY: number, initialPosX: number, initialPosY: number } | null>(null);

  const { data: projects } = useProjects({ active_only: true, limit: 500 });
  const { data: tasks } = useTasks(projectId ? { project_id: projectId, active_only: true } : undefined);

  const activeProject = projects?.find((p: any) => p.id === projectId);
  const activeTask = tasks?.find((t: any) => t.id === taskId);

  useEffect(() => {
    const saved = localStorage.getItem('acufy_timer_float_pos');
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        const x = Math.max(0, Math.min(parsed.x, window.innerWidth - 220));
        const y = Math.max(0, Math.min(parsed.y, window.innerHeight - 150));
        setPos({ x, y });
      } catch (e) {}
    }
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!dragRef.current) return;
      const dx = e.clientX - dragRef.current.startX;
      const dy = e.clientY - dragRef.current.startY;
      setPos({
        x: Math.max(0, Math.min(dragRef.current.initialPosX + dx, window.innerWidth - 220)),
        y: Math.max(0, Math.min(dragRef.current.initialPosY + dy, window.innerHeight - 100))
      });
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      localStorage.setItem('acufy_timer_float_pos', JSON.stringify(pos));
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, pos]);

  if (status === 'idle' || status === 'stopped') {
    return null;
  }

  const handleMouseDown = (e: React.MouseEvent) => {
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      initialPosX: pos.x,
      initialPosY: pos.y
    };
    setIsDragging(true);
  };

  const widgetContent = minimized ? (
    <div
      className="flex items-center justify-center gap-3 px-4 py-2 w-[120px] h-[36px] bg-card border border-primary/30 rounded-full shadow-lg cursor-pointer hover:border-primary transition-colors"
      onClick={() => setMinimized(false)}
      style={{ left: pos.x, top: pos.y, position: 'fixed', zIndex: 9999 }}
    >
      <div className={cn("w-2 h-2 rounded-full", status === 'running' ? "bg-primary animate-pulse" : "bg-amber-500")} />
      <span className="font-mono text-sm font-bold text-foreground">
        {formatElapsed(elapsedMs)}
      </span>
    </div>
  ) : (
    <div
      className="w-[220px] bg-card/90 backdrop-blur-xl border border-primary/20 rounded-2xl shadow-[0_8px_32px_rgba(0,0,0,0.4)] flex flex-col overflow-hidden"
      style={{ left: pos.x, top: pos.y, position: 'fixed', zIndex: 9999 }}
    >
      <div
        className="flex items-center justify-between px-3 py-2 bg-muted/40 cursor-grab active:cursor-grabbing border-b border-border/50"
        onMouseDown={handleMouseDown}
      >
        <GripHorizontal className="h-4 w-4 text-muted-foreground" />
        <div className="flex items-center gap-2">
          <button onClick={() => setMinimized(true)} className="text-muted-foreground hover:text-foreground">
            <Minus className="h-4 w-4" />
          </button>
          <button onClick={discard} className="text-muted-foreground hover:text-destructive">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="px-4 py-4 flex flex-col items-center">
        <div className={cn("text-3xl font-mono font-bold tracking-tight mb-2", status === 'running' ? "text-primary" : "text-amber-500")}>
          {formatElapsed(elapsedMs)}
        </div>
        <p className="text-xs text-muted-foreground text-center truncate w-full px-2">
          {activeProject ? `${activeProject.name}` : 'No Project'}
          {activeTask ? ` · ${activeTask.name}` : ''}
        </p>
      </div>

      <div className="flex items-center justify-between px-4 py-3 bg-muted/20 border-t border-border/50 gap-2">
        {status === 'running' ? (
          <button
            onClick={pause}
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg bg-amber-500/10 text-amber-500 font-medium text-xs hover:bg-amber-500/20 transition"
          >
            <Pause className="h-3 w-3 fill-current" /> Pause
          </button>
        ) : (
          <button
            onClick={resume}
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg bg-primary/10 text-primary font-medium text-xs hover:bg-primary/20 transition"
          >
            <Play className="h-3 w-3 fill-current" /> Resume
          </button>
        )}
        <button
          onClick={stop}
          className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg bg-destructive/10 text-destructive font-medium text-xs hover:bg-destructive/20 transition"
        >
          <Square className="h-3 w-3 fill-current" /> Stop
        </button>
      </div>
    </div>
  );

  return createPortal(widgetContent, document.body);
};
