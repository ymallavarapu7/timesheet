import React, { useCallback, useMemo, useState } from 'react';
import { format, parseISO, startOfWeek } from 'date-fns';
import { ArrowDown, ArrowUp, CheckCircle, ChevronDown, ChevronRight, Clock, XCircle } from 'lucide-react';

import { EmptyState, Error, Loading, SearchInput } from '@/components';
import {
  useApprovalHistoryGrouped,
  useApproveTimeEntryBatch,
  usePendingApprovals,
  useRejectTimeEntry,
  useRejectTimeEntryBatch,
  useRevertTimeEntryRejection,
  usePendingTimeOffApprovals,
  useApproveTimeOffRequest,
  useRejectTimeOffRequest,
  useWeekStartsOn,
} from '@/hooks';
import type { HistoryGroup } from '@/api/endpoints';
import { TimeEntry, TimeOffRequest } from '@/types';

type EmployeeOverview = {
  id: number;
  name: string;
  timesheetCount: number;
};

type WeeklyTimesheetGroup = {
  employeeId: number;
  employeeName: string;
  weekStart: string;
  weekEnd: string;
  items: TimeEntry[];
};

const parseEntryDate = (value: string) => parseISO(value);

const groupTimesheetsByEmployeeWeek = (items: TimeEntry[], weekStartsOn: 0 | 1): WeeklyTimesheetGroup[] => {
  const grouped = new Map<string, WeeklyTimesheetGroup>();

  items.forEach((item) => {
    const weekStartDate = startOfWeek(parseEntryDate(item.entry_date), { weekStartsOn });
    const weekEndDate = new Date(weekStartDate);
    weekEndDate.setDate(weekEndDate.getDate() + 6);
    const weekStart = format(weekStartDate, 'yyyy-MM-dd');
    const weekEnd = format(weekEndDate, 'yyyy-MM-dd');
    const groupKey = `${item.user_id}-${weekStart}`;

    const existing = grouped.get(groupKey);
    if (existing) {
      existing.items.push(item);
      return;
    }

    grouped.set(groupKey, {
      employeeId: item.user_id,
      employeeName: item.user?.full_name || 'Unknown Employee',
      weekStart,
      weekEnd,
      items: [item],
    });
  });

  return Array.from(grouped.values())
    .map((group) => ({
      ...group,
      items: group.items.sort((a, b) => parseEntryDate(a.entry_date).getTime() - parseEntryDate(b.entry_date).getTime()),
    }))
    .sort((a, b) => {
      const nameCmp = a.employeeName.localeCompare(b.employeeName);
      if (nameCmp !== 0) return nameCmp;
      return b.weekStart.localeCompare(a.weekStart);
    });
};

export const ApprovalsPage: React.FC = () => {
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState<'entry_date' | 'submitted_at' | 'hours' | 'employee'>('submitted_at');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [rejectionReasons, setRejectionReasons] = useState<Record<string, string>>({});
  const [showRejectForm, setShowRejectForm] = useState<Record<string, boolean>>({});
  const [rejectingEntryId, setRejectingEntryId] = useState<number | null>(null);
  const [entryRejectReason, setEntryRejectReason] = useState('');
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<number | null>(null);
  const [historyDaysBack, setHistoryDaysBack] = useState(30);
  const [historyStatusFilter, setHistoryStatusFilter] = useState<'' | 'approved' | 'rejected' | 'mixed'>('');
  const [expandedHistoryKeys, setExpandedHistoryKeys] = useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = useState<'timesheets' | 'time-off'>('timesheets');
  const [rejectingTimeOffId, setRejectingTimeOffId] = useState<number | null>(null);
  const [timeOffRejectReason, setTimeOffRejectReason] = useState('');
  const [statusMessage, setStatusMessage] = useState('');
  const [statusTone, setStatusTone] = useState<'success' | 'danger'>('success');

  const showStatus = useCallback((message: string, tone: 'success' | 'danger') => {
    setStatusMessage(message);
    setStatusTone(tone);
    setTimeout(() => setStatusMessage(''), 5000);
  }, []);

  const params = useMemo(
    () => ({ search: search.trim() || undefined, sort_by: sortBy, sort_order: sortOrder, limit: 500 }),
    [search, sortBy, sortOrder]
  );

  const { data: timeEntries, isLoading: timeLoading, error: timeError } = usePendingApprovals(params);
  const historyGroupedParams = useMemo(
    () => ({ days_back: historyDaysBack, status_filter: historyStatusFilter || undefined }),
    [historyDaysBack, historyStatusFilter]
  );
  const { data: historyGroups = [], isLoading: historyLoading, error: historyError } = useApprovalHistoryGrouped(historyGroupedParams);

  const searchSuggestions = useMemo(() => {
    const set = new Set<string>();
    (timeEntries ?? []).forEach((e: TimeEntry) => {
      if (e.user?.full_name) set.add(e.user.full_name);
      if (e.project?.name) set.add(e.project.name);
      if (e.rejection_reason) set.add(e.rejection_reason);
    });
    historyGroups.forEach((g: HistoryGroup) => {
      set.add(g.employee_name);
      g.entries.forEach((e) => { if (e.project_name) set.add(e.project_name); });
    });
    return Array.from(set).filter(Boolean).sort();
  }, [timeEntries, historyGroups]);

  const approveBatchMutation = useApproveTimeEntryBatch();
  const rejectBatchMutation = useRejectTimeEntryBatch();
  const [selectedGroupKeys, setSelectedGroupKeys] = useState<Set<string>>(new Set());
  const [bulkRejectReason, setBulkRejectReason] = useState('');
  const [showBulkRejectForm, setShowBulkRejectForm] = useState(false);
  const rejectEntryMutation = useRejectTimeEntry();
  const revertRejectionMutation = useRevertTimeEntryRejection();

  const { data: pendingTimeOff = [], isLoading: timeOffLoading } = usePendingTimeOffApprovals();
  const approveTimeOffMutation = useApproveTimeOffRequest();
  const rejectTimeOffMutation = useRejectTimeOffRequest();

  const weekStartsOn = useWeekStartsOn();

  // All grouping / memos must be BEFORE early returns (Rules of Hooks)
  const timesheetWeeklyGroups = useMemo(
    () => groupTimesheetsByEmployeeWeek((timeEntries ?? []) as TimeEntry[], weekStartsOn),
    [timeEntries, weekStartsOn]
  );
  const employeeOverview: EmployeeOverview[] = useMemo(() => {
    const map = new Map<number, EmployeeOverview>();
    timesheetWeeklyGroups.forEach((g) => {
      const existing = map.get(g.employeeId);
      if (existing) {
        existing.timesheetCount += 1;
      } else {
        map.set(g.employeeId, { id: g.employeeId, name: g.employeeName, timesheetCount: 1 });
      }
    });
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [timesheetWeeklyGroups]);

  const displayTimesheetWeeklyGroups = useMemo(
    () => selectedEmployeeId === null ? timesheetWeeklyGroups : timesheetWeeklyGroups.filter((g) => g.employeeId === selectedEmployeeId),
    [timesheetWeeklyGroups, selectedEmployeeId]
  );
  const historyDisplayGroups = useMemo(() => {
    let groups = historyGroups as HistoryGroup[];
    if (selectedEmployeeId !== null) groups = groups.filter((g) => g.employee_id === selectedEmployeeId);
    if (search.trim()) {
      const term = search.trim().toLowerCase();
      groups = groups.filter((g) =>
        g.employee_name.toLowerCase().includes(term) ||
        g.entries.some((e) => (e.project_name ?? '').toLowerCase().includes(term) || (e.description ?? '').toLowerCase().includes(term))
      );
    }
    return groups;
  }, [historyGroups, selectedEmployeeId, search]);

  const getGroupKey = (group: { employeeId: number; weekStart: string }) => `${group.employeeId}-${group.weekStart}`;

  const selectedEntryIds = useMemo(() => {
    const ids: number[] = [];
    for (const group of displayTimesheetWeeklyGroups) {
      if (selectedGroupKeys.has(getGroupKey(group))) {
        for (const entry of group.items) ids.push(entry.id);
      }
    }
    return ids;
  }, [displayTimesheetWeeklyGroups, selectedGroupKeys]);

  if (timeLoading && !timeEntries) {
    return <Loading />;
  }

  if (timeError || historyError) {
    return <Error message="Failed to load approvals" />;
  }

  const hasNoEntries = timesheetWeeklyGroups.length === 0;

  const handleApproveTimesheetWeek = async (entryIds: number[]) => {
    try {
      await approveBatchMutation.mutateAsync(entryIds);
      showStatus(`Approved ${entryIds.length} entries.`, 'success');
    } catch (error) {
      console.error('Error approving timesheet week:', error);
      showStatus('Some approvals failed. Please refresh and try again.', 'danger');
    }
  };

  const handleRejectTimesheetWeek = async (entryIds: number[], key: string) => {
    const reason = rejectionReasons[key] || '';
    if (!reason.trim()) {
      alert('Please provide a rejection reason');
      return;
    }

    try {
      await rejectBatchMutation.mutateAsync({ entryIds, reason });
      setShowRejectForm((current) => ({ ...current, [key]: false }));
      setRejectionReasons((current) => ({ ...current, [key]: '' }));
      showStatus(`Rejected ${entryIds.length} entries.`, 'success');
    } catch (error) {
      console.error('Error rejecting timesheet week:', error);
      showStatus('Some rejections failed. Please refresh and try again.', 'danger');
    }
  };

  // ── Bulk select + approve/reject across week groups ──
  const toggleGroupSelection = (key: string) => {
    setSelectedGroupKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const selectAllGroups = () => {
    setSelectedGroupKeys(new Set(displayTimesheetWeeklyGroups.map(getGroupKey)));
  };

  const clearGroupSelection = () => {
    setSelectedGroupKeys(new Set());
    setShowBulkRejectForm(false);
    setBulkRejectReason('');
  };

  const handleBulkApprove = async () => {
    if (selectedEntryIds.length === 0) return;
    if (!window.confirm(`Approve ${selectedEntryIds.length} time entries across ${selectedGroupKeys.size} employee-week groups?`)) return;
    try {
      await approveBatchMutation.mutateAsync(selectedEntryIds);
      showStatus(`Approved ${selectedEntryIds.length} entries.`, 'success');
      clearGroupSelection();
    } catch {
      showStatus('Some approvals failed. Please refresh and try again.', 'danger');
    }
  };

  const handleBulkReject = async () => {
    if (selectedEntryIds.length === 0 || !bulkRejectReason.trim()) return;
    try {
      await rejectBatchMutation.mutateAsync({ entryIds: selectedEntryIds, reason: bulkRejectReason.trim() });
      showStatus(`Rejected ${selectedEntryIds.length} entries.`, 'success');
      clearGroupSelection();
    } catch {
      showStatus('Some rejections failed. Please refresh and try again.', 'danger');
    }
  };

  return (
    <div>
      <div>
        <h1 className="text-3xl font-bold mb-6">Pending Approvals</h1>

        {statusMessage && (
          <div className={`mb-4 px-4 py-3 rounded text-sm font-medium ${
            statusTone === 'success'
              ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
              : 'bg-red-50 text-red-800 border border-red-200'
          }`}>
            {statusMessage}
          </div>
        )}

        {/* Tab switcher */}
        <div className="flex gap-1 mb-6 border-b">
          <button
            onClick={() => setActiveTab('timesheets')}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === 'timesheets'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            Timesheets
          </button>
          <button
            onClick={() => setActiveTab('time-off')}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === 'time-off'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            Time Off
            {(pendingTimeOff as TimeOffRequest[]).length > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center min-w-5 h-5 px-1.5 rounded-full text-[11px] font-bold bg-red-500 text-white">
                {(pendingTimeOff as TimeOffRequest[]).length > 99 ? '99+' : (pendingTimeOff as TimeOffRequest[]).length}
              </span>
            )}
          </button>
        </div>

        {activeTab === 'timesheets' && (<>
        {/* Employee Overview Selector */}
        {!hasNoEntries && (
          <div className="mb-6">
            <p className="text-sm font-medium text-muted-foreground mb-3">Filter by employee</p>
            <div className="flex flex-wrap gap-3">
              {/* All Employees card */}
              <button
                onClick={() => setSelectedEmployeeId(null)}
                className={`flex flex-col items-center px-4 py-3 rounded-xl border-2 transition-all min-w-[100px] ${
                  selectedEmployeeId === null
                    ? 'border-primary bg-primary text-primary-foreground shadow-md'
                    : 'border-border bg-card hover:border-primary/50 hover:shadow-sm'
                }`}
              >
                <span className="text-sm font-semibold">All</span>
                <span className={`text-2xl font-bold leading-none mt-1 ${selectedEmployeeId === null ? 'text-primary-foreground' : 'text-foreground'}`}>
                  {employeeOverview.reduce((sum, e) => sum + e.timesheetCount, 0)}
                </span>
                <span className={`text-[11px] mt-1 ${selectedEmployeeId === null ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>
                  total pending
                </span>
              </button>

              {/* Per-employee cards */}
              {employeeOverview.map((emp) => {
                const isSelected = selectedEmployeeId === emp.id;
                const total = emp.timesheetCount;
                return (
                  <button
                    key={emp.id}
                    onClick={() => setSelectedEmployeeId(isSelected ? null : emp.id)}
                    className={`relative flex flex-col px-4 py-3 rounded-xl border-2 transition-all min-w-[140px] text-left ${
                      isSelected
                        ? 'border-primary bg-primary text-primary-foreground shadow-md'
                        : 'border-border bg-card hover:border-primary/50 hover:shadow-sm'
                    }`}
                  >
                    {/* Total badge */}
                    <span className={`absolute -top-2 -right-2 min-w-5 h-5 px-1.5 rounded-full text-[11px] font-bold flex items-center justify-center ${
                      isSelected ? 'bg-white text-primary' : 'bg-red-500 text-white'
                    }`}>
                      {total > 99 ? '99+' : total}
                    </span>

                    {/* Employee name */}
                    <span className="text-sm font-semibold leading-tight mb-2 pr-4">
                      {emp.name}
                    </span>

                    {/* Breakdown badges */}
                    <div className="flex gap-1.5 flex-wrap">
                      {emp.timesheetCount > 0 && (
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${
                          isSelected ? 'bg-white/20 text-primary-foreground' : 'bg-blue-100 text-blue-800'
                        }`}>
                          <Clock className="w-3 h-3" />
                          {emp.timesheetCount} timesheet
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <div className="bg-card border rounded-lg p-4 mb-4 grid grid-cols-1 gap-3">
          <SearchInput
            value={search}
            onChange={setSearch}
            suggestions={searchSuggestions}
            placeholder="Search employee/project/reason"
            className="px-3 py-2 border rounded w-full"
          />
        </div>

        <div className="mb-6 flex items-center justify-end gap-2">
          <select
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value as 'entry_date' | 'submitted_at' | 'hours' | 'employee')}
            className="h-9 w-40 rounded border bg-card px-2 text-xs"
          >
            <option value="submitted_at">Submitted At</option>
            <option value="entry_date">Date</option>
            <option value="hours">Hours</option>
            <option value="employee">Employee</option>
          </select>
          <button
            onClick={() => setSortOrder((value) => (value === 'asc' ? 'desc' : 'asc'))}
            className="h-9 w-9 rounded border hover:bg-muted flex items-center justify-center"
            aria-label={sortOrder === 'asc' ? 'Sort ascending' : 'Sort descending'}
            title={sortOrder === 'asc' ? 'Ascending' : 'Descending'}
          >
            {sortOrder === 'asc' ? <ArrowUp className="w-4 h-4" /> : <ArrowDown className="w-4 h-4" />}
          </button>
        </div>

        {hasNoEntries && <EmptyState message="No pending approvals. All entries have been reviewed!" />}

        {displayTimesheetWeeklyGroups.length > 0 && (
          <div className="mb-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold">Timesheet Approvals</h2>
              {displayTimesheetWeeklyGroups.length > 1 && (
                <div className="flex items-center gap-2 text-sm">
                  <button
                    type="button"
                    onClick={selectedGroupKeys.size === displayTimesheetWeeklyGroups.length ? clearGroupSelection : selectAllGroups}
                    className="text-primary font-medium hover:text-primary/80"
                  >
                    {selectedGroupKeys.size === displayTimesheetWeeklyGroups.length ? 'Clear selection' : 'Select all'}
                  </button>
                </div>
              )}
            </div>

            {/* Bulk action bar */}
            {selectedGroupKeys.size > 0 && (
              <div className="mb-4 rounded-lg border border-primary/20 bg-primary/5 px-4 py-3">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <span className="text-sm font-medium text-foreground">
                    {selectedGroupKeys.size} week group{selectedGroupKeys.size !== 1 ? 's' : ''} selected · {selectedEntryIds.length} entries
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleBulkApprove}
                      disabled={approveBatchMutation.isPending}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary/90 disabled:opacity-50"
                    >
                      <CheckCircle className="h-3.5 w-3.5" />
                      {approveBatchMutation.isPending ? 'Approving...' : `Approve all (${selectedEntryIds.length})`}
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowBulkRejectForm((v) => !v)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-destructive px-3 py-1.5 text-xs font-semibold text-white hover:bg-destructive/90"
                    >
                      <XCircle className="h-3.5 w-3.5" />
                      Reject all
                    </button>
                    <button
                      type="button"
                      onClick={clearGroupSelection}
                      className="text-xs text-muted-foreground hover:text-foreground"
                    >
                      Clear
                    </button>
                  </div>
                </div>
                {showBulkRejectForm && (
                  <div className="mt-3 space-y-2">
                    <textarea
                      value={bulkRejectReason}
                      onChange={(e) => setBulkRejectReason(e.target.value)}
                      placeholder="Rejection reason (applied to all selected entries)..."
                      className="field-textarea"
                      rows={2}
                    />
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={handleBulkReject}
                        disabled={rejectBatchMutation.isPending || !bulkRejectReason.trim()}
                        className="rounded-lg bg-destructive px-3 py-1.5 text-xs font-semibold text-white hover:bg-destructive/90 disabled:opacity-50"
                      >
                        {rejectBatchMutation.isPending ? 'Rejecting...' : 'Confirm reject'}
                      </button>
                      <button
                        type="button"
                        onClick={() => { setShowBulkRejectForm(false); setBulkRejectReason(''); }}
                        className="rounded-lg bg-muted px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted/80"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="space-y-4">
              {displayTimesheetWeeklyGroups.map((group) => (
                <section key={`timesheet-${group.employeeId}-${group.weekStart}`} className="border rounded-lg bg-card overflow-hidden">
                  <div className="px-6 py-4 border-b bg-muted/30 flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={selectedGroupKeys.has(getGroupKey(group))}
                      onChange={() => toggleGroupSelection(getGroupKey(group))}
                      className="h-4 w-4 rounded border-border accent-primary"
                    />
                    <div className="flex-1">
                      <h3 className="text-lg font-semibold">{group.employeeName}</h3>
                      <p className="text-sm text-muted-foreground">
                        Week of {format(parseISO(group.weekStart), 'MMM d, yyyy')} - {format(parseISO(group.weekEnd), 'MMM d, yyyy')} • {group.items.length} submitted entr{group.items.length === 1 ? 'y' : 'ies'}
                      </p>
                    </div>
                  </div>

                  <div className="p-4 space-y-4">
                    {(() => {
                      const key = `timesheet-week-${group.employeeId}-${group.weekStart}`;
                      const entryIds = group.items.map((entry) => entry.id);
                      return (
                        <div className="border rounded-lg p-6 bg-card">
                          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
                            <div>
                              <p className="text-sm text-muted-foreground">Week</p>
                              <p className="font-medium">{format(parseISO(group.weekStart), 'MMM d')} - {format(parseISO(group.weekEnd), 'MMM d, yyyy')}</p>
                            </div>
                            <div>
                              <p className="text-sm text-muted-foreground">Employee</p>
                              <p className="font-medium">{group.employeeName}</p>
                            </div>
                            <div>
                              <p className="text-sm text-muted-foreground">Entries</p>
                              <p className="font-medium">{group.items.length}</p>
                            </div>
                            <div>
                              <p className="text-sm text-muted-foreground">Hours (total)</p>
                              <p className="font-medium">{group.items.reduce((sum, item) => sum + Number(item.hours), 0).toFixed(2)}</p>
                            </div>
                          </div>

                          <div className="mb-4 space-y-2">
                            {group.items.map((entry) => (
                              <div key={entry.id} className="text-sm border rounded px-3 py-2">
                                <div className="flex items-start justify-between gap-2">
                                  <div className="min-w-0">
                                    <p className="font-medium">{format(parseEntryDate(entry.entry_date), 'EEE, MMM d')} • {entry.hours}h • {entry.project?.name || 'Unknown project'}</p>
                                    <p className="text-muted-foreground">{entry.description}</p>
                                  </div>
                                  <button
                                    onClick={() => { setRejectingEntryId(entry.id); setEntryRejectReason(''); }}
                                    className="shrink-0 px-2 py-1 text-xs border border-red-200 text-red-600 rounded hover:bg-red-50"
                                  >
                                    Reject Entry
                                  </button>
                                </div>
                                {rejectingEntryId === entry.id && (
                                  <div className="mt-2 flex gap-2">
                                    <input
                                      className="flex-1 px-2 py-1 border rounded text-xs"
                                      value={entryRejectReason}
                                      onChange={(e) => setEntryRejectReason(e.target.value)}
                                      placeholder="Rejection reason (required)"
                                      autoFocus
                                    />
                                    <button
                                      onClick={async () => {
                                        if (!entryRejectReason.trim()) return;
                                        try {
                                          await rejectEntryMutation.mutateAsync({ id: entry.id, reason: entryRejectReason });
                                          setRejectingEntryId(null);
                                          setEntryRejectReason('');
                                          showStatus('Time entry rejected.', 'success');
                                        } catch (err) {
                                          console.error('Error rejecting entry:', err);
                                          showStatus('Rejection failed. Please try again.', 'danger');
                                        }
                                      }}
                                      disabled={!entryRejectReason.trim() || rejectEntryMutation.isPending}
                                      className="px-2 py-1 text-xs bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
                                    >
                                      Confirm
                                    </button>
                                    <button
                                      onClick={() => { setRejectingEntryId(null); setEntryRejectReason(''); }}
                                      className="px-2 py-1 text-xs border rounded hover:bg-muted"
                                    >
                                      Cancel
                                    </button>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>

                          {!showRejectForm[key] ? (
                            <div className="flex gap-2">
                              <button
                                onClick={() => handleApproveTimesheetWeek(entryIds)}
                                disabled={approveBatchMutation.isPending}
                                className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/80 disabled:opacity-50"
                              >
                                <CheckCircle className="w-4 h-4" />
                                {approveBatchMutation.isPending ? 'Approving week...' : 'Approve Week'}
                              </button>
                              <button
                                onClick={() => setShowRejectForm((current) => ({ ...current, [key]: true }))}
                                className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
                              >
                                <XCircle className="w-4 h-4" />
                                Reject Week
                              </button>
                            </div>
                          ) : (
                            <div className="space-y-2">
                              <textarea
                                value={rejectionReasons[key] || ''}
                                onChange={(event) => setRejectionReasons((current) => ({ ...current, [key]: event.target.value }))}
                                placeholder="Rejection reason for this week..."
                                className="w-full px-3 py-2 border rounded"
                                rows={3}
                              />
                              <div className="flex gap-2">
                                <button
                                  onClick={() => handleRejectTimesheetWeek(entryIds, key)}
                                  disabled={rejectBatchMutation.isPending}
                                  className="flex-1 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
                                >
                                  {rejectBatchMutation.isPending ? 'Rejecting week...' : 'Confirm Week Rejection'}
                                </button>
                                <button
                                  onClick={() => setShowRejectForm((current) => ({ ...current, [key]: false }))}
                                  className="flex-1 px-4 py-2 bg-muted text-muted-foreground rounded hover:bg-muted/90"
                                >
                                  Cancel
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })()}
                  </div>
                </section>
              ))}
            </div>
          </div>
        )}

        <div className="mt-10">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-xl font-bold">Approval History</h2>
            <div className="flex items-center gap-2 flex-wrap">
              {/* Status filter tabs */}
              {(['', 'approved', 'rejected', 'mixed'] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setHistoryStatusFilter(f)}
                  className={`px-3 py-1.5 rounded-full text-xs font-medium border transition ${
                    historyStatusFilter === f
                      ? f === '' ? 'bg-slate-700 text-white border-slate-700'
                        : f === 'approved' ? 'bg-emerald-600 text-white border-emerald-600'
                        : f === 'rejected' ? 'bg-red-600 text-white border-red-600'
                        : 'bg-amber-500 text-white border-amber-500'
                      : 'bg-card border-border hover:bg-muted'
                  }`}
                >
                  {f === '' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
                </button>
              ))}
              {/* Days back selector */}
              <select
                value={historyDaysBack}
                onChange={(e) => setHistoryDaysBack(Number(e.target.value))}
                className="h-8 rounded border bg-card px-2 text-xs"
              >
                <option value={7}>Last 7 days</option>
                <option value={30}>Last 30 days</option>
                <option value={90}>Last 90 days</option>
                <option value={365}>Last year</option>
              </select>
            </div>
          </div>

          {historyLoading ? (
            <Loading />
          ) : historyDisplayGroups.length === 0 ? (
            <EmptyState message="No approval history for the selected filters." />
          ) : (
            <div className="rounded-xl border bg-white shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 border-b text-left">
                  <tr>
                    <th className="px-4 py-3 font-semibold text-slate-700 w-6"></th>
                    <th className="px-4 py-3 font-semibold text-slate-700">Employee</th>
                    <th className="px-4 py-3 font-semibold text-slate-700">Week</th>
                    <th className="px-4 py-3 font-semibold text-slate-700">Hours</th>
                    <th className="px-4 py-3 font-semibold text-slate-700">Entries</th>
                    <th className="px-4 py-3 font-semibold text-slate-700">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {historyDisplayGroups.map((group) => {
                    const key = `${group.employee_id}-${group.week_start}`;
                    const isExpanded = expandedHistoryKeys.has(key);
                    const toggleExpand = () => setExpandedHistoryKeys((prev) => {
                      const next = new Set(prev);
                      next.has(key) ? next.delete(key) : next.add(key);
                      return next;
                    });
                    const statusColors = group.status === 'approved'
                      ? 'bg-emerald-100 text-emerald-700'
                      : group.status === 'rejected'
                        ? 'bg-red-100 text-red-700'
                        : 'bg-amber-100 text-amber-700';
                    return (
                      <React.Fragment key={key}>
                        <tr
                          className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                          onClick={toggleExpand}
                        >
                          <td className="px-4 py-3 text-slate-400 text-xs select-none">
                            {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                          </td>
                          <td className="px-4 py-3 font-medium text-slate-900">{group.employee_name}</td>
                          <td className="px-4 py-3 text-slate-600">
                            {format(parseISO(group.week_start), 'MMM d')} – {format(parseISO(group.week_end), 'MMM d, yyyy')}
                          </td>
                          <td className="px-4 py-3 font-medium text-slate-900">{group.total_hours.toFixed(1)}h</td>
                          <td className="px-4 py-3 text-slate-600">{group.entry_count}</td>
                          <td className="px-4 py-3">
                            <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${statusColors}`}>
                              {group.status.charAt(0).toUpperCase() + group.status.slice(1)}
                              {group.status === 'mixed' && (
                                <span className="ml-1 text-[10px] opacity-75">
                                  ({group.approved_count}✓ {group.rejected_count}✗)
                                </span>
                              )}
                            </span>
                          </td>
                        </tr>
                        {isExpanded && group.entries.map((entry) => (
                          <tr key={entry.id} className="bg-slate-50/70 border-t border-slate-100">
                            <td className="px-4 py-2"></td>
                            <td className="px-4 py-2 text-slate-400 text-xs">↳</td>
                            <td className="px-4 py-2 text-xs text-slate-600">
                              <span className="font-medium">{format(parseISO(entry.entry_date), 'EEE, MMM d')}</span>
                              {entry.project_name && <span className="ml-2 text-slate-400">· {entry.project_name}</span>}
                              {entry.description && <p className="text-slate-400 mt-0.5">{entry.description}</p>}
                              {entry.rejection_reason && (
                                <p className="text-red-600 mt-0.5">Reason: {entry.rejection_reason}</p>
                              )}
                            </td>
                            <td className="px-4 py-2 text-xs font-medium text-slate-700">{entry.hours}h</td>
                            <td></td>
                            <td className="px-4 py-2">
                              <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium ${
                                entry.status === 'APPROVED' ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
                              }`}>
                                {entry.status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
        </>)}

        {activeTab === 'time-off' && (
          <div>
            {timeOffLoading ? (
              <Loading />
            ) : (pendingTimeOff as TimeOffRequest[]).length === 0 ? (
              <EmptyState message="No pending time off requests." />
            ) : (
              <div className="space-y-4">
                {(pendingTimeOff as TimeOffRequest[]).map((req) => (
                  <div key={req.id} className="border rounded-lg p-4 bg-white">
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <span className="font-medium">{req.user?.full_name ?? '—'}</span>
                        <span className="ml-2 text-xs px-2 py-0.5 rounded bg-blue-100 text-blue-700">{req.leave_type}</span>
                      </div>
                      <span className="text-sm text-slate-500">{req.request_date}</span>
                    </div>
                    <p className="text-sm text-slate-600 mb-1">{req.reason || '—'}</p>
                    <p className="text-sm font-medium mb-3">{Number(req.hours)}h</p>
                    {rejectingTimeOffId === req.id ? (
                      <div className="flex gap-2 items-center">
                        <input
                          className="flex-1 border rounded px-2 py-1 text-sm"
                          placeholder="Rejection reason..."
                          value={timeOffRejectReason}
                          onChange={(e) => setTimeOffRejectReason(e.target.value)}
                        />
                        <button
                          className="px-3 py-1 bg-red-600 text-white rounded text-sm"
                          onClick={() => {
                            rejectTimeOffMutation.mutate(
                              { id: req.id, reason: timeOffRejectReason },
                              {
                                onSuccess: () => { setRejectingTimeOffId(null); setTimeOffRejectReason(''); showStatus('Time entry rejected.', 'success'); },
                                onError: (err) => { console.error('Error rejecting time off:', err); showStatus('Rejection failed. Please try again.', 'danger'); },
                              }
                            );
                          }}
                        >Confirm</button>
                        <button className="px-3 py-1 border rounded text-sm" onClick={() => setRejectingTimeOffId(null)}>Cancel</button>
                      </div>
                    ) : (
                      <div className="flex gap-2">
                        <button
                          className="px-3 py-1.5 bg-emerald-600 text-white rounded text-sm hover:bg-emerald-700"
                          onClick={() => approveTimeOffMutation.mutate(req.id, {
                            onSuccess: () => showStatus('Time entry approved.', 'success'),
                            onError: (err) => { console.error('Error approving time off:', err); showStatus('Approval failed. Please try again.', 'danger'); },
                          })}
                        >Approve</button>
                        <button
                          className="px-3 py-1.5 border border-red-300 text-red-600 rounded text-sm hover:bg-red-50"
                          onClick={() => { setRejectingTimeOffId(req.id); setTimeOffRejectReason(''); }}
                        >Reject</button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
