import { useCallback, useSyncExternalStore } from 'react';

export type WidgetKey =
  | 'total'
  | 'today'
  | 'util'
  | 'productivity'
  | 'overtime'
  | 'tproject'
  | 'barchart'
  | 'activity'
  | 'projects'
  | 'timeoff';

export interface WidgetDef {
  key: WidgetKey;
  label: string;
  description: string;
  defaultSpan: number;
  defaultVisible: boolean;
  group: 'overview' | 'projects' | 'leave';
}

export const WIDGET_REGISTRY: WidgetDef[] = [
  { key: 'total', label: 'Total Time', description: 'Weekly total hours with trend', defaultSpan: 3, defaultVisible: true, group: 'overview' },
  { key: 'today', label: "Today's Time", description: "Hours logged today", defaultSpan: 2, defaultVisible: true, group: 'overview' },
  { key: 'util', label: 'Utilization', description: '% of target hours hit', defaultSpan: 2, defaultVisible: true, group: 'overview' },
  { key: 'productivity', label: 'Productivity', description: 'Billable vs Non-billable', defaultSpan: 4, defaultVisible: false, group: 'overview' },
  { key: 'overtime', label: 'Overtime', description: 'Hours beyond weekly target', defaultSpan: 2, defaultVisible: false, group: 'overview' },
  { key: 'tproject', label: 'Top Project', description: 'Most logged project this week', defaultSpan: 2, defaultVisible: true, group: 'projects' },
  { key: 'barchart', label: 'Daily Breakdown', description: 'Bar chart of daily hours', defaultSpan: 8, defaultVisible: true, group: 'projects' },
  { key: 'activity', label: 'Top Activities', description: 'Most tracked tasks ranked', defaultSpan: 4, defaultVisible: true, group: 'projects' },
  { key: 'projects', label: 'Projects Breakdown', description: 'Hours & share per project', defaultSpan: 4, defaultVisible: true, group: 'projects' },
  { key: 'timeoff', label: 'Time Off Balance', description: 'Leave days remaining', defaultSpan: 4, defaultVisible: true, group: 'leave' },
];

export type WidgetVisibility = Record<WidgetKey, boolean>;

const STORAGE_KEY = 'acufy_dashboard_widgets';

function getDefaults(): WidgetVisibility {
  const result = {} as WidgetVisibility;
  for (const w of WIDGET_REGISTRY) {
    result[w.key] = w.defaultVisible;
  }
  return result;
}

function readStore(): WidgetVisibility {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return getDefaults();
    const parsed = JSON.parse(raw) as Partial<WidgetVisibility>;
    const defaults = getDefaults();
    for (const key of Object.keys(defaults) as WidgetKey[]) {
      if (typeof parsed[key] === 'boolean') {
        defaults[key] = parsed[key]!;
      }
    }
    return defaults;
  } catch {
    return getDefaults();
  }
}

function writeStore(state: WidgetVisibility) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

let currentState = readStore();
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return currentState;
}

function setState(next: WidgetVisibility) {
  currentState = next;
  writeStore(next);
  listeners.forEach((l) => l());
}

export function useWidgetPreferences() {
  const state = useSyncExternalStore(subscribe, getSnapshot);

  const toggleWidget = useCallback((key: WidgetKey) => {
    const next = { ...getSnapshot(), [key]: !getSnapshot()[key] };
    setState(next);
  }, []);

  const setWidgetVisible = useCallback((key: WidgetKey, visible: boolean) => {
    const next = { ...getSnapshot(), [key]: visible };
    setState(next);
  }, []);

  const isVisible = useCallback((key: WidgetKey) => state[key], [state]);

  const resetToDefaults = useCallback(() => {
    setState(getDefaults());
  }, []);

  return { state, toggleWidget, setWidgetVisible, isVisible, resetToDefaults };
}
