import React, { useEffect, useState } from 'react';
import { useTenantSettings, useUpdateTenantSettings } from '@/hooks';
import { TenantSettingsForm } from '@/components/TenantSettingsForm';

// Back-compat: settings API now returns typed values; coerce so the legacy
// string-based form keeps working. TODO: drop with the legacy form.
const toStringish = (v: unknown): string | null => {
  if (v == null) return null;
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  return String(v);
};

export const AdminSettingsPage: React.FC = () => {
  const { data: rawTenantSettings = {} } = useTenantSettings();
  const updateSettings = useUpdateTenantSettings();

  // Normalise every value to ``string | null`` for the legacy form below.
  const tenantSettings: Record<string, string | null> = Object.fromEntries(
    Object.entries(rawTenantSettings ?? {}).map(([k, v]) => [k, toStringish(v)])
  );

  const [settingsSaved, setSettingsSaved] = useState(false);
  const flashSaved = () => {
    setSettingsSaved(true);
    setTimeout(() => setSettingsSaved(false), 2000);
  };

  const [pastDays, setPastDays] = useState('14');
  const [futureDays, setFutureDays] = useState('0');

  // Hour limits
  const [maxPerEntry, setMaxPerEntry] = useState('24');
  const [maxPerDay, setMaxPerDay] = useState('24');
  const [maxPerWeek, setMaxPerWeek] = useState('80');
  const [minSubmitWeekly, setMinSubmitWeekly] = useState('1');

  // Submission policy
  const [allowPartialWeek, setAllowPartialWeek] = useState(false);
  const [weekStartDay, setWeekStartDay] = useState('0');

  // Time-off policy
  const [timeOffPast, setTimeOffPast] = useState('14');
  const [timeOffFuture, setTimeOffFuture] = useState('365');
  const [timeOffAdvance, setTimeOffAdvance] = useState('0');
  const [timeOffMaxConsecutive, setTimeOffMaxConsecutive] = useState('0');
  const [allowOverlappingTimeOff, setAllowOverlappingTimeOff] = useState(false);

  // Security
  const [maxFailedAttempts, setMaxFailedAttempts] = useState('5');
  const [lockoutMinutes, setLockoutMinutes] = useState('15');

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
    if (tenantSettings.time_entry_past_days != null) setPastDays(tenantSettings.time_entry_past_days);
    if (tenantSettings.time_entry_future_days != null) setFutureDays(tenantSettings.time_entry_future_days);
    if (tenantSettings.max_hours_per_entry != null) setMaxPerEntry(tenantSettings.max_hours_per_entry);
    if (tenantSettings.max_hours_per_day != null) setMaxPerDay(tenantSettings.max_hours_per_day);
    if (tenantSettings.max_hours_per_week != null) setMaxPerWeek(tenantSettings.max_hours_per_week);
    if (tenantSettings.min_submit_weekly_hours != null) setMinSubmitWeekly(tenantSettings.min_submit_weekly_hours);
    if (tenantSettings.allow_partial_week_submit != null) setAllowPartialWeek(tenantSettings.allow_partial_week_submit === 'true');
    if (tenantSettings.week_start_day != null) setWeekStartDay(tenantSettings.week_start_day);
    if (tenantSettings.time_off_past_days != null) setTimeOffPast(tenantSettings.time_off_past_days);
    if (tenantSettings.time_off_future_days != null) setTimeOffFuture(tenantSettings.time_off_future_days);
    if (tenantSettings.time_off_advance_notice_days != null) setTimeOffAdvance(tenantSettings.time_off_advance_notice_days);
    if (tenantSettings.time_off_max_consecutive_days != null) setTimeOffMaxConsecutive(tenantSettings.time_off_max_consecutive_days);
    if (tenantSettings.allow_overlapping_time_off != null) setAllowOverlappingTimeOff(tenantSettings.allow_overlapping_time_off === 'true');
    if (tenantSettings.max_failed_login_attempts != null) setMaxFailedAttempts(tenantSettings.max_failed_login_attempts);
    if (tenantSettings.lockout_duration_minutes != null) setLockoutMinutes(tenantSettings.lockout_duration_minutes);
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
        {/* Time Entry Window */}
        <div className="rounded-xl border border-border bg-card shadow-sm p-6">
          <div className="mb-4">
            <h3 className="text-base font-semibold">Time entry window</h3>
            <p className="text-sm text-muted-foreground mt-0.5">
              How far back and forward employees can log or submit time entries. Affects everyone in the tenant.
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Days in the past</label>
              <input
                type="number"
                min="0"
                max="365"
                className="field-input"
                value={pastDays}
                onChange={(e) => setPastDays(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">e.g. 14 = employees can log time up to 14 days back.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Days in the future</label>
              <input
                type="number"
                min="0"
                max="365"
                className="field-input"
                value={futureDays}
                onChange={(e) => setFutureDays(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">0 = future entries are not allowed.</p>
            </div>
          </div>
          <div className="flex justify-end mt-4">
            <button
              className="action-button text-sm disabled:opacity-50"
              disabled={updateSettings.isPending}
              onClick={() => {
                const past = String(Math.max(0, parseInt(pastDays || '0', 10) || 0));
                const future = String(Math.max(0, parseInt(futureDays || '0', 10) || 0));
                setPastDays(past);
                setFutureDays(future);
                updateSettings.mutate(
                  { time_entry_past_days: past, time_entry_future_days: future },
                  { onSuccess: flashSaved },
                );
              }}
            >
              {settingsSaved ? 'Saved!' : 'Save'}
            </button>
          </div>
        </div>

        {/* Hour limits */}
        <div className="rounded-xl border border-border bg-card shadow-sm p-6">
          <div className="mb-4">
            <h3 className="text-base font-semibold">Hour limits</h3>
            <p className="text-sm text-muted-foreground mt-0.5">Upper bounds on the hours an employee can log per entry, day, and week, plus the minimum to submit a week.</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Max hours per entry</label>
              <input type="number" min="0" step="0.5" className="field-input" value={maxPerEntry} onChange={(e) => setMaxPerEntry(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Max hours per day</label>
              <input type="number" min="0" step="0.5" className="field-input" value={maxPerDay} onChange={(e) => setMaxPerDay(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Max hours per week</label>
              <input type="number" min="0" step="0.5" className="field-input" value={maxPerWeek} onChange={(e) => setMaxPerWeek(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Minimum hours to submit a week</label>
              <input type="number" min="0" step="0.5" className="field-input" value={minSubmitWeekly} onChange={(e) => setMinSubmitWeekly(e.target.value)} />
              <p className="text-xs text-muted-foreground mt-1">Weeks below this total are blocked from submission (unless empty weeks are allowed).</p>
            </div>
          </div>
          <div className="flex justify-end mt-4">
            <button
              className="action-button text-sm disabled:opacity-50"
              disabled={updateSettings.isPending}
              onClick={() => {
                updateSettings.mutate(
                  {
                    max_hours_per_entry: maxPerEntry,
                    max_hours_per_day: maxPerDay,
                    max_hours_per_week: maxPerWeek,
                    min_submit_weekly_hours: minSubmitWeekly,
                  },
                  { onSuccess: flashSaved },
                );
              }}
            >
              {settingsSaved ? 'Saved!' : 'Save'}
            </button>
          </div>
        </div>

        {/* Submission policy */}
        <div className="rounded-xl border border-border bg-card shadow-sm p-6">
          <div className="mb-4">
            <h3 className="text-base font-semibold">Submission policy</h3>
            <p className="text-sm text-muted-foreground mt-0.5">How employees submit time for approval.</p>
          </div>
          <div className="space-y-3">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-foreground">First day of the week</p>
                <p className="text-xs text-muted-foreground">Affects how weekly totals and grids are grouped.</p>
              </div>
              <select className="field-input w-auto" value={weekStartDay} onChange={(e) => setWeekStartDay(e.target.value)}>
                <option value="0">Sunday</option>
                <option value="1">Monday</option>
              </select>
            </div>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-foreground">Allow submitting part of a week</p>
                <p className="text-xs text-muted-foreground">When off, employees must submit every draft entry for that week together.</p>
              </div>
              <input type="checkbox" className="h-5 w-5 cursor-pointer" checked={allowPartialWeek} onChange={(e) => setAllowPartialWeek(e.target.checked)} />
            </div>
          </div>
          <div className="flex justify-end mt-4">
            <button
              className="action-button text-sm disabled:opacity-50"
              disabled={updateSettings.isPending}
              onClick={() => {
                updateSettings.mutate(
                  {
                    week_start_day: weekStartDay,
                    allow_partial_week_submit: String(allowPartialWeek),
                  },
                  { onSuccess: flashSaved },
                );
              }}
            >
              {settingsSaved ? 'Saved!' : 'Save'}
            </button>
          </div>
        </div>

        {/* Time-off policy */}
        <div className="rounded-xl border border-border bg-card shadow-sm p-6">
          <div className="mb-4">
            <h3 className="text-base font-semibold">Time-off policy</h3>
            <p className="text-sm text-muted-foreground mt-0.5">Rules for when and how time-off requests can be created.</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Days in the past</label>
              <input type="number" min="0" className="field-input" value={timeOffPast} onChange={(e) => setTimeOffPast(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Days in the future</label>
              <input type="number" min="0" className="field-input" value={timeOffFuture} onChange={(e) => setTimeOffFuture(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Advance notice required (days)</label>
              <input type="number" min="0" className="field-input" value={timeOffAdvance} onChange={(e) => setTimeOffAdvance(e.target.value)} />
              <p className="text-xs text-muted-foreground mt-1">0 = no minimum notice. Applies to future-dated requests only.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Max consecutive days</label>
              <input type="number" min="0" className="field-input" value={timeOffMaxConsecutive} onChange={(e) => setTimeOffMaxConsecutive(e.target.value)} />
              <p className="text-xs text-muted-foreground mt-1">0 = no limit.</p>
            </div>
          </div>
          <div className="mt-4 flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-foreground">Allow overlapping time off</p>
              <p className="text-xs text-muted-foreground">When off, an employee can have only one time-off request per date.</p>
            </div>
            <input type="checkbox" className="h-5 w-5 cursor-pointer" checked={allowOverlappingTimeOff} onChange={(e) => setAllowOverlappingTimeOff(e.target.checked)} />
          </div>
          <div className="flex justify-end mt-4">
            <button
              className="action-button text-sm disabled:opacity-50"
              disabled={updateSettings.isPending}
              onClick={() => {
                updateSettings.mutate(
                  {
                    time_off_past_days: timeOffPast,
                    time_off_future_days: timeOffFuture,
                    time_off_advance_notice_days: timeOffAdvance,
                    time_off_max_consecutive_days: timeOffMaxConsecutive,
                    allow_overlapping_time_off: String(allowOverlappingTimeOff),
                  },
                  { onSuccess: flashSaved },
                );
              }}
            >
              {settingsSaved ? 'Saved!' : 'Save'}
            </button>
          </div>
        </div>

        {/* Security policy */}
        <div className="rounded-xl border border-border bg-card shadow-sm p-6">
          <div className="mb-4">
            <h3 className="text-base font-semibold">Security</h3>
            <p className="text-sm text-muted-foreground mt-0.5">Login lockout behavior after repeated failed attempts.</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Max failed login attempts</label>
              <input type="number" min="1" className="field-input" value={maxFailedAttempts} onChange={(e) => setMaxFailedAttempts(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Lockout duration (minutes)</label>
              <input type="number" min="1" className="field-input" value={lockoutMinutes} onChange={(e) => setLockoutMinutes(e.target.value)} />
            </div>
          </div>
          <div className="flex justify-end mt-4">
            <button
              className="action-button text-sm disabled:opacity-50"
              disabled={updateSettings.isPending}
              onClick={() => {
                updateSettings.mutate(
                  {
                    max_failed_login_attempts: maxFailedAttempts,
                    lockout_duration_minutes: lockoutMinutes,
                  },
                  { onSuccess: flashSaved },
                );
              }}
            >
              {settingsSaved ? 'Saved!' : 'Save'}
            </button>
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
              <p className="text-sm text-muted-foreground mt-0.5">Send monthly reminders to external contractors who haven't submitted this month</p>
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

      {/* New catalog-driven form (side-by-side rollout). TODO: drop the legacy form. */}
      <div className="mt-8">
        <TenantSettingsForm />
      </div>
    </div>
  );
};
