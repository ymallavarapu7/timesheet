/**
 * Catalog-driven tenant-settings form.
 *
 * Reads the ``setting_definitions`` catalog from the backend and renders
 * each setting with a widget appropriate to its ``data_type``, grouped by
 * category and ordered by ``sort_order``. All submissions go through the
 * same ``PATCH /users/tenant-settings`` endpoint as the legacy form in
 * ``AdminSettingsPage``, which now validates against the same catalog
 * server-side.
 *
 * Rendered side-by-side with the legacy form during rollout. When this
 * form is verified in production, the legacy form (and the
 * ``toStringish`` shim in ``AdminSettingsPage``) should be removed.
 */
import React, { useEffect, useMemo, useState } from 'react';

import {
  useTenantSettings,
  useTenantSettingsCatalog,
  useUpdateTenantSettings,
} from '@/hooks';
import type { SettingDefinition, SettingValue } from '@/api/endpoints';

// Categories rendered in this order; any category returned by the backend
// that isn't listed here appears at the end, unordered.
const CATEGORY_ORDER: Array<{ key: string; label: string }> = [
  { key: 'time_entry', label: 'Time entry' },
  { key: 'time_off', label: 'Time off' },
  { key: 'security', label: 'Security' },
  { key: 'reminders', label: 'Reminders' },
  { key: 'notifications', label: 'Notifications' },
  { key: 'email', label: 'Email / SMTP' },
];

// ``smtp_password`` has its own dedicated (encrypted) entry flow elsewhere
// in the admin UI. Skip rendering it here so operators don't accidentally
// overwrite a stored secret with the catalog default (empty string) by
// clicking Save without touching the field.
const SKIP_KEYS = new Set<string>(['smtp_password']);

type Errors = Record<string, string | undefined>;

export const TenantSettingsForm: React.FC = () => {
  const catalogQuery = useTenantSettingsCatalog();
  const valuesQuery = useTenantSettings();
  const updateMutation = useUpdateTenantSettings();

  // Local working copy of the form values. Keyed by setting key.
  const [draft, setDraft] = useState<Record<string, SettingValue>>({});
  const [errors, setErrors] = useState<Errors>({});
  const [saveFlash, setSaveFlash] = useState<'idle' | 'saved' | 'error'>('idle');

  // Seed the draft from the server values whenever they change.
  useEffect(() => {
    if (valuesQuery.data) {
      setDraft((existing) => ({ ...valuesQuery.data, ...existing }));
    }
    // Only seed once per response; don't fight user edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valuesQuery.data]);

  const grouped = useMemo(() => {
    const catalog = catalogQuery.data ?? [];
    const byCategory = new Map<string, SettingDefinition[]>();
    for (const defn of catalog) {
      if (SKIP_KEYS.has(defn.key)) continue;
      const list = byCategory.get(defn.category) ?? [];
      list.push(defn);
      byCategory.set(defn.category, list);
    }
    for (const list of byCategory.values()) {
      list.sort((a, b) => a.sort_order - b.sort_order || a.key.localeCompare(b.key));
    }
    const ordered = CATEGORY_ORDER
      .filter((c) => byCategory.has(c.key))
      .map((c) => ({ label: c.label, defs: byCategory.get(c.key)! }));
    // Trailing "unknown" categories — shouldn't happen in practice but keep
    // the UI graceful if a new category is added server-side before the
    // frontend is updated.
    const knownKeys = new Set(CATEGORY_ORDER.map((c) => c.key));
    for (const [key, defs] of byCategory.entries()) {
      if (!knownKeys.has(key)) ordered.push({ label: key, defs });
    }
    return ordered;
  }, [catalogQuery.data]);

  if (catalogQuery.isLoading || valuesQuery.isLoading) {
    return (
      <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
        Loading settings catalog…
      </div>
    );
  }

  if (catalogQuery.isError) {
    return (
      <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
        Failed to load the settings catalog. Refresh to retry.
      </div>
    );
  }

  const setValue = (key: string, value: SettingValue) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
  };

  const handleSave = async () => {
    // Only send keys whose value differs from the server snapshot.
    const server = valuesQuery.data ?? {};
    const payload: Record<string, SettingValue> = {};
    for (const [k, v] of Object.entries(draft)) {
      if (SKIP_KEYS.has(k)) continue;
      if (JSON.stringify(v) !== JSON.stringify(server[k])) {
        payload[k] = v;
      }
    }
    if (Object.keys(payload).length === 0) {
      setSaveFlash('saved');
      window.setTimeout(() => setSaveFlash('idle'), 2000);
      return;
    }
    try {
      await updateMutation.mutateAsync(payload);
      setErrors({});
      setSaveFlash('saved');
      window.setTimeout(() => setSaveFlash('idle'), 2000);
    } catch (exc: unknown) {
      // Server returns 422 with a per-key-or-general detail string.
      const detail =
        (exc as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed.';
      // We don't know which key failed from the detail alone — surface a
      // form-level error.
      setErrors({ __form: detail });
      setSaveFlash('error');
      window.setTimeout(() => setSaveFlash('idle'), 4000);
    }
  };

  return (
    <div className="rounded-lg border bg-card">
      <div className="border-b px-4 py-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-muted-foreground">
            All settings (catalog-driven)
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Every tenant setting, rendered from the server catalog. Fields are
            validated server-side when you save.
          </p>
        </div>
        <button
          className="action-button text-sm disabled:opacity-50"
          onClick={handleSave}
          disabled={updateMutation.isPending}
        >
          {saveFlash === 'saved'
            ? 'Saved!'
            : saveFlash === 'error'
            ? 'Error'
            : updateMutation.isPending
            ? 'Saving…'
            : 'Save changes'}
        </button>
      </div>

      {errors.__form && (
        <div className="border-b border-destructive/40 bg-destructive/5 px-4 py-2 text-sm text-destructive">
          {errors.__form}
        </div>
      )}

      <div className="divide-y">
        {grouped.map((group) => (
          <section key={group.label} className="px-4 py-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
              {group.label}
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
              {group.defs.map((defn) => (
                <SettingField
                  key={defn.key}
                  defn={defn}
                  value={draft[defn.key] ?? defn.default_value}
                  onChange={(v) => setValue(defn.key, v)}
                  error={errors[defn.key]}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Per-field widget
// ─────────────────────────────────────────────────────────────────────────────

interface SettingFieldProps {
  defn: SettingDefinition;
  value: SettingValue;
  onChange: (v: SettingValue) => void;
  error?: string;
}

const SettingField: React.FC<SettingFieldProps> = ({ defn, value, onChange, error }) => {
  const labelId = `setting-${defn.key}`;
  const helpId = `setting-${defn.key}-help`;

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={labelId} className="text-sm font-medium">
        {defn.label}
      </label>
      <Widget defn={defn} value={value} onChange={onChange} labelId={labelId} />
      <p id={helpId} className="text-xs text-muted-foreground">
        {defn.description}
      </p>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
};

interface WidgetProps {
  defn: SettingDefinition;
  value: SettingValue;
  onChange: (v: SettingValue) => void;
  labelId: string;
}

const Widget: React.FC<WidgetProps> = ({ defn, value, onChange, labelId }) => {
  const { data_type, validation } = defn;

  if (data_type === 'bool') {
    const checked = Boolean(value);
    return (
      <label className="inline-flex items-center gap-2">
        <input
          id={labelId}
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className="text-sm">{checked ? 'Enabled' : 'Disabled'}</span>
      </label>
    );
  }

  if (data_type === 'string' && validation.enum) {
    return (
      <select
        id={labelId}
        className="field-input"
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
      >
        {validation.enum.map((opt) => (
          <option key={String(opt)} value={String(opt)}>
            {String(opt)}
          </option>
        ))}
      </select>
    );
  }

  if (data_type === 'string') {
    return (
      <input
        id={labelId}
        type="text"
        className="field-input"
        value={String(value ?? '')}
        minLength={validation.min_length}
        maxLength={validation.max_length}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  if (data_type === 'time') {
    return (
      <input
        id={labelId}
        type="time"
        className="field-input"
        value={typeof value === 'string' ? value : '00:00'}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  if (data_type === 'int' && validation.enum) {
    // Small enum-of-ints renders as a select for clearer affordance.
    return (
      <select
        id={labelId}
        className="field-input"
        value={String(value ?? 0)}
        onChange={(e) => onChange(Number(e.target.value))}
      >
        {validation.enum.map((opt) => (
          <option key={String(opt)} value={String(opt)}>
            {String(opt)}
          </option>
        ))}
      </select>
    );
  }

  if (data_type === 'int' || data_type === 'float') {
    const numeric = typeof value === 'number' ? value : Number(value) || 0;
    return (
      <input
        id={labelId}
        type="number"
        className="field-input"
        value={numeric}
        step={data_type === 'int' ? 1 : 0.1}
        min={validation.min}
        max={validation.max}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === '') {
            onChange(0);
            return;
          }
          onChange(data_type === 'int' ? Math.trunc(Number(raw)) : Number(raw));
        }}
      />
    );
  }

  // json or unknown — fall back to a textarea that preserves the raw JSON.
  return (
    <textarea
      id={labelId}
      className="field-textarea"
      rows={3}
      value={value == null ? '' : JSON.stringify(value)}
      onChange={(e) => {
        try {
          onChange(JSON.parse(e.target.value));
        } catch {
          /* leave unchanged until it parses */
        }
      }}
    />
  );
};
