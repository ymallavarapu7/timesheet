import { useCallback, useSyncExternalStore } from 'react';
import { WIDGET_REGISTRY, type WidgetKey } from './useWidgetPreferences';

export type WidgetSizes = Record<WidgetKey, number>;
export type WidgetOrder = WidgetKey[];

export interface DashboardPrefs {
  visible: Record<WidgetKey, boolean>;
  order: WidgetOrder;
  sizes: WidgetSizes;
}

export const ALLOWED_SIZES: Record<WidgetKey, number[]> = {
  total:        [3, 4, 6],
  today:        [2, 3],
  util:         [2, 3],
  productivity: [4, 6],
  overtime:     [2, 3],
  tproject:     [2, 3, 4],
  barchart:     [6, 8, 12],
  activity:     [4, 6, 8],
  projects:     [4, 6, 8],
  timeoff:      [3, 4, 6],
};

const STORAGE_KEY = 'acufy_dashboard';

function getDefaults(): DashboardPrefs {
  const visible = {} as Record<WidgetKey, boolean>;
  const sizes = {} as WidgetSizes;
  const order: WidgetOrder = [];

  for (const w of WIDGET_REGISTRY) {
    visible[w.key] = w.defaultVisible;
    sizes[w.key] = w.defaultSpan;
    order.push(w.key);
  }

  return { visible, order, sizes };
}

function readStore(): DashboardPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return getDefaults();
    const parsed = JSON.parse(raw) as Partial<DashboardPrefs>;
    const defaults = getDefaults();

    if (parsed.visible) {
      for (const key of Object.keys(defaults.visible) as WidgetKey[]) {
        if (typeof parsed.visible[key] === 'boolean') {
          defaults.visible[key] = parsed.visible[key]!;
        }
      }
    }

    if (parsed.sizes) {
      for (const key of Object.keys(defaults.sizes) as WidgetKey[]) {
        if (typeof parsed.sizes[key] === 'number') {
          defaults.sizes[key] = parsed.sizes[key]!;
        }
      }
    }

    if (parsed.order && Array.isArray(parsed.order)) {
      const validKeys = new Set(Object.keys(defaults.visible) as WidgetKey[]);
      const storedOrder = parsed.order.filter((k: WidgetKey) => validKeys.has(k));
      for (const key of defaults.order) {
        if (!storedOrder.includes(key)) {
          storedOrder.push(key);
        }
      }
      defaults.order = storedOrder;
    }

    return defaults;
  } catch {
    return getDefaults();
  }
}

function writeStore(state: DashboardPrefs) {
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

function setState(next: DashboardPrefs) {
  currentState = next;
  writeStore(next);
  listeners.forEach((l) => l());
}

export function useDashboardPrefs() {
  const state = useSyncExternalStore(subscribe, getSnapshot);

  const toggleWidget = useCallback((key: WidgetKey) => {
    const snap = getSnapshot();
    setState({
      ...snap,
      visible: { ...snap.visible, [key]: !snap.visible[key] },
    });
  }, []);

  const setWidgetVisible = useCallback((key: WidgetKey, visible: boolean) => {
    const snap = getSnapshot();
    setState({
      ...snap,
      visible: { ...snap.visible, [key]: visible },
    });
  }, []);

  const isVisible = useCallback((key: WidgetKey) => state.visible[key], [state]);

  const setOrder = useCallback((order: WidgetOrder) => {
    const snap = getSnapshot();
    setState({ ...snap, order });
  }, []);

  const setSize = useCallback((key: WidgetKey, size: number) => {
    const snap = getSnapshot();
    setState({
      ...snap,
      sizes: { ...snap.sizes, [key]: size },
    });
  }, []);

  const cycleSize = useCallback((key: WidgetKey) => {
    const snap = getSnapshot();
    const allowed = ALLOWED_SIZES[key];
    if (!allowed || allowed.length <= 1) return;
    const currentSize = snap.sizes[key];
    const currentIdx = allowed.indexOf(currentSize);
    const nextIdx = (currentIdx + 1) % allowed.length;
    setState({
      ...snap,
      sizes: { ...snap.sizes, [key]: allowed[nextIdx] },
    });
  }, []);

  const resetToDefaults = useCallback(() => {
    setState(getDefaults());
  }, []);

  return {
    prefs: state,
    toggleWidget,
    setWidgetVisible,
    isVisible,
    setOrder,
    setSize,
    cycleSize,
    resetToDefaults,
  };
}
