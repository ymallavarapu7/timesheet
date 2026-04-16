import React, { useEffect, useState } from 'react';
import { useTenantSettings, useUpdateTenantSettings } from '@/hooks';

export const AdminSettingsPage: React.FC = () => {
  const { data: tenantSettings = {} } = useTenantSettings();
  const updateSettings = useUpdateTenantSettings();

  const [settingsSaved, setSettingsSaved] = useState(false);
  const flashSaved = () => {
    setSettingsSaved(true);
    setTimeout(() => setSettingsSaved(false), 2000);
  };

  const [allowFutureEntries, setAllowFutureEntries] = useState(false);
  const [internalEnabled, setInternalEnabled] = useState(false);
  const [internalDeadlineDay, setInternalDeadlineDay] = useState('friday');
  const [internalDeadlineTime, setInternalDeadlineTime] = useState('17:00');
  const [internalLockEnabled, setInternalLockEnabled] = useState(false);
  const [internalRecipients, setInternalRecipients] = useState('all');
  const [externalEnabled, setExternalEnabled] = useState(false);
  const [externalDeadlineDayOffset, setExternalDeadlineDayOffset] = useState('-2');
  const [externalDeadlineTime, setExternalDeadlineTime] = useState('17:00');

  useEffect(() => {
    if (!tenantSettings || Object.keys(tenantSettings).length === 0) return;
    setAllowFutureEntries(tenantSettings.allow_future_entries === 'true');
    if (tenantSettings.reminder_internal_enabled) setInternalEnabled(tenantSettings.reminder_internal_enabled === 'true');
    if (tenantSettings.reminder_internal_deadline_day) setInternalDeadlineDay(tenantSettings.reminder_internal_deadline_day);
    if (tenantSettings.reminder_internal_deadline_time) setInternalDeadlineTime(tenantSettings.reminder_internal_deadline_time);
    if (tenantSettings.reminder_internal_lock_enabled) setInternalLockEnabled(tenantSettings.reminder_internal_lock_enabled === 'true');
    if (tenantSettings.reminder_internal_recipients) setInternalRecipients(tenantSettings.reminder_internal_recipients);
    if (tenantSettings.reminder_external_enabled) setExternalEnabled(tenantSettings.reminder_external_enabled === 'true');
    if (tenantSettings.reminder_external_deadline_day_of_month) setExternalDeadlineDayOffset(tenantSettings.reminder_external_deadline_day_of_month);
    if (tenantSettings.reminder_external_deadline_time) setExternalDeadlineTime(tenantSettings.reminder_external_deadline_time);
  }, [tenantSettings]);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">Tenant-wide policies and reminder configuration.</p>
      </div>

      <div className="space-y-6">
        {/* Time Entry Policy */}
        <div className="rounded-xl border border-border bg-card shadow-sm p-6">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-base font-semibold">Allow future-dated time entries</h3>
              <p className="text-sm text-muted-foreground mt-0.5">When enabled, anyone who submits time can log hours on dates in the future.</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                className="sr-only peer"
                checked={allowFutureEntries}
                onChange={(e) => {
                  const next = e.target.checked;
                  setAllowFutureEntries(next);
                  updateSettings.mutate(
                    { allow_future_entries: String(next) },
                    { onSuccess: flashSaved },
                  );
                }}
              />
              <div className="w-11 h-6 bg-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-border after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
            </label>
          </div>
        </div>

        {/* Internal Reminders */}
        <div className="rounded-xl border border-border bg-card shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-base font-semibold">Internal Employee Reminders</h3>
              <p className="text-sm text-muted-foreground mt-0.5">Send weekly submission reminders to employees</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" className="sr-only peer" checked={internalEnabled} onChange={(e) => setInternalEnabled(e.target.checked)} />
              <div className="w-11 h-6 bg-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-border after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
            </label>
          </div>
          {internalEnabled && (
            <div className="space-y-4 pt-2 border-t">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Deadline Day</label>
                  <select className="field-input" value={internalDeadlineDay} onChange={(e) => setInternalDeadlineDay(e.target.value)}>
                    {['monday','tuesday','wednesday','thursday','friday'].map(d => (
                      <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Deadline Time</label>
                  <input type="time" className="field-input" value={internalDeadlineTime} onChange={(e) => setInternalDeadlineTime(e.target.value)} />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <label className="relative inline-flex items-center cursor-pointer">
                  <input type="checkbox" className="sr-only peer" checked={internalLockEnabled} onChange={(e) => setInternalLockEnabled(e.target.checked)} />
                  <div className="w-9 h-5 bg-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-border after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-primary"></div>
                </label>
                <span className="text-sm text-foreground">Lock timesheet if deadline is missed</span>
              </div>
            </div>
          )}
          <div className="flex justify-end mt-4">
            <button
              className="action-button text-sm disabled:opacity-50"
              disabled={updateSettings.isPending}
              onClick={() => {
                updateSettings.mutate({
                  reminder_internal_enabled: String(internalEnabled),
                  reminder_internal_deadline_day: internalDeadlineDay,
                  reminder_internal_deadline_time: internalDeadlineTime,
                  reminder_internal_lock_enabled: String(internalLockEnabled),
                  reminder_internal_recipients: internalRecipients,
                }, { onSuccess: flashSaved });
              }}
            >
              {settingsSaved ? 'Saved!' : 'Save'}
            </button>
          </div>
        </div>

        {/* External Contractor Reminders */}
        <div className="rounded-xl border border-border bg-card shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-base font-semibold">External Contractor Reminders</h3>
              <p className="text-sm text-muted-foreground mt-0.5">Send monthly reminders to contractors with sender mappings</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" className="sr-only peer" checked={externalEnabled} onChange={(e) => setExternalEnabled(e.target.checked)} />
              <div className="w-11 h-6 bg-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-border after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
            </label>
          </div>
          {externalEnabled && (
            <div className="space-y-4 pt-2 border-t">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Days before month end</label>
                  <input type="number" min="-28" max="-1" className="field-input" value={externalDeadlineDayOffset} onChange={(e) => setExternalDeadlineDayOffset(e.target.value)} />
                  <p className="text-xs text-muted-foreground mt-1">e.g. -2 = 2 days before end of month</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Deadline Time</label>
                  <input type="time" className="field-input" value={externalDeadlineTime} onChange={(e) => setExternalDeadlineTime(e.target.value)} />
                </div>
              </div>
            </div>
          )}
          <div className="flex justify-end mt-4">
            <button
              className="action-button text-sm disabled:opacity-50"
              disabled={updateSettings.isPending}
              onClick={() => {
                updateSettings.mutate({
                  reminder_external_enabled: String(externalEnabled),
                  reminder_external_deadline_day_of_month: externalDeadlineDayOffset,
                  reminder_external_deadline_time: externalDeadlineTime,
                }, { onSuccess: flashSaved });
              }}
            >
              {settingsSaved ? 'Saved!' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
