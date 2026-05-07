import { openDB, DBSchema } from 'idb';

export interface TimerState {
  id: 'current';
  status: 'idle' | 'running' | 'paused' | 'stopped';
  startTimestamp: number | null;
  accumulatedMs: number;
  projectId: number | null;
  taskId: number | null;
  notes: string;
  lastUpdated: number;
}

interface AcufyTimerDB extends DBSchema {
  timer_state: {
    key: 'current';
    value: TimerState;
  };
}

const DB_NAME = 'acufy_timer_db';
const DB_VERSION = 1;

async function initDB() {
  return openDB<AcufyTimerDB>(DB_NAME, DB_VERSION, {
    upgrade(db) {
      if (!db.objectStoreNames.contains('timer_state')) {
        db.createObjectStore('timer_state', { keyPath: 'id' });
      }
    },
  });
}

const defaultState: TimerState = {
  id: 'current',
  status: 'idle',
  startTimestamp: null,
  accumulatedMs: 0,
  projectId: null,
  taskId: null,
  notes: '',
  lastUpdated: Date.now(),
};

export async function getTimerState(): Promise<TimerState> {
  const db = await initDB();
  const state = await db.get('timer_state', 'current');
  return state || defaultState;
}

export async function setTimerState(patch: Partial<TimerState>): Promise<void> {
  const db = await initDB();
  const tx = db.transaction('timer_state', 'readwrite');
  const store = tx.objectStore('timer_state');

  let current = await store.get('current');
  if (!current) {
    current = { ...defaultState };
  }

  const newState: TimerState = {
    ...current,
    ...patch,
    id: 'current',
    lastUpdated: Date.now()
  };

  await store.put(newState);
  await tx.done;
}

export async function clearTimerState(): Promise<void> {
  const db = await initDB();
  await db.put('timer_state', {
    ...defaultState,
    lastUpdated: Date.now()
  });
}
