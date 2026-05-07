import React, { createContext, useCallback, useEffect, useState, useRef } from 'react';
import { getTimerState, setTimerState, clearTimerState, TimerState } from '@/lib/timerDB';
import { pingServiceWorker, notifyServiceWorker } from '@/lib/registerTimerSW';

export interface TimerContextValue {
  status: 'idle' | 'running' | 'paused' | 'stopped';
  elapsedMs: number;
  startTimestamp: number | null;
  accumulatedMs: number;
  projectId: number | null;
  taskId: number | null;
  notes: string;
  start: () => void;
  pause: () => void;
  resume: () => void;
  stop: () => void;
  discard: () => void;
  setProject: (id: number | null) => void;
  setTask: (id: number | null) => void;
  setNotes: (n: string) => void;
}

export const TimerContext = createContext<TimerContextValue | null>(null);

export const TimerProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, setState] = useState<TimerState>({
    id: 'current',
    status: 'idle',
    startTimestamp: null,
    accumulatedMs: 0,
    projectId: null,
    taskId: null,
    notes: '',
    lastUpdated: Date.now(),
  });
  const [elapsedMs, setElapsedMs] = useState(0);
  const bcRef = useRef<BroadcastChannel | null>(null);
  const stateRef = useRef(state);

  const broadcastState = useCallback((newState: TimerState) => {
    if (bcRef.current) {
      bcRef.current.postMessage({ type: 'SYNC_STATE', state: newState });
    }
  }, []);

  useEffect(() => {
    bcRef.current = new BroadcastChannel('acufy_timer');

    bcRef.current.onmessage = (event) => {
      if (event.data.type === 'SYNC_STATE') {
        setState(event.data.state);
      }
    };

    async function init() {
      const stored = await getTimerState();
      let newElapsedMs = stored.accumulatedMs;

      if (stored.status === 'running' && stored.startTimestamp) {
        try {
          const swRes = await pingServiceWorker();
          newElapsedMs = swRes.elapsedMs;
        } catch (e) {
          newElapsedMs = stored.accumulatedMs + (Date.now() - stored.startTimestamp);
        }
      }

      setState(stored);
      setElapsedMs(newElapsedMs);
    }

    init();

    return () => {
      bcRef.current?.close();
    };
  }, []);

  useEffect(() => {
    let frameId: number;
    let lastUpdate = 0;

    function tick(timestamp: number) {
      if (timestamp - lastUpdate > 16) {
        if (state.status === 'running' && state.startTimestamp) {
          setElapsedMs(state.accumulatedMs + (Date.now() - state.startTimestamp));
        } else if (state.status !== 'running') {
          setElapsedMs(state.accumulatedMs);
        }
        lastUpdate = timestamp;
      }
      frameId = requestAnimationFrame(tick);
    }

    frameId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameId);
  }, [state.status, state.startTimestamp, state.accumulatedMs]);

  useEffect(() => { stateRef.current = state; }, [state]);

  const updateState = useCallback(async (patch: Partial<TimerState>) => {
    const latest = stateRef.current;
    const newState = { ...latest, ...patch, lastUpdated: Date.now() };
    setState(newState);
    stateRef.current = newState;
    await setTimerState(patch);
    broadcastState(newState);
  }, [broadcastState]);

  const start = useCallback(async () => {
    const now = Date.now();
    await updateState({
      status: 'running',
      startTimestamp: now,
      accumulatedMs: 0
    });
    notifyServiceWorker('TIMER_START', { startTimestamp: now, accumulatedMs: 0 });
  }, [updateState]);

  const pause = useCallback(async () => {
    const now = Date.now();
    const s = stateRef.current;
    const addMs = s.startTimestamp ? (now - s.startTimestamp) : 0;
    const newAccumulated = s.accumulatedMs + addMs;

    await updateState({
      status: 'paused',
      startTimestamp: null,
      accumulatedMs: newAccumulated
    });
    notifyServiceWorker('TIMER_PAUSE');
  }, [updateState]);

  const resume = useCallback(async () => {
    const now = Date.now();
    const s = stateRef.current;
    await updateState({
      status: 'running',
      startTimestamp: now
    });
    notifyServiceWorker('TIMER_RESUME', { startTimestamp: now, accumulatedMs: s.accumulatedMs });
  }, [updateState]);

  const stop = useCallback(async () => {
    const s = stateRef.current;
    let newAccumulated = s.accumulatedMs;
    if (s.status === 'running' && s.startTimestamp) {
      newAccumulated += Date.now() - s.startTimestamp;
    }

    await updateState({
      status: 'stopped',
      startTimestamp: null,
      accumulatedMs: newAccumulated
    });
    notifyServiceWorker('TIMER_STOP');
  }, [updateState]);

  const discard = useCallback(async () => {
    await clearTimerState();
    const emptyState: TimerState = {
      id: 'current',
      status: 'idle',
      startTimestamp: null,
      accumulatedMs: 0,
      projectId: null,
      taskId: null,
      notes: '',
      lastUpdated: Date.now()
    };
    setState(emptyState);
    setElapsedMs(0);
    broadcastState(emptyState);
    notifyServiceWorker('TIMER_STOP');
  }, [broadcastState]);

  const setProject = useCallback((id: number | null) => { updateState({ projectId: id }); }, [updateState]);
  const setTask = useCallback((id: number | null) => { updateState({ taskId: id }); }, [updateState]);
  const setNotes = useCallback((notes: string) => { updateState({ notes }); }, [updateState]);

  const value: TimerContextValue = {
    status: state.status,
    elapsedMs,
    startTimestamp: state.startTimestamp,
    accumulatedMs: state.accumulatedMs,
    projectId: state.projectId,
    taskId: state.taskId,
    notes: state.notes,
    start,
    pause,
    resume,
    stop,
    discard,
    setProject,
    setTask,
    setNotes
  };

  return <TimerContext.Provider value={value}>{children}</TimerContext.Provider>;
};
