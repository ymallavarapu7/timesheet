import React, { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Loading, Error, EmptyState, SearchInput } from '@/components';
import {
  useCreateTimeOffRequest,
  useDeleteTimeOffRequest,
  useSubmitTimeOffRequests,
  useTimeOffRequests,
  useUpdateTimeOffRequest,
} from '@/hooks';
import { TimeOffRequest, TimeOffStatus, TimeOffType } from '@/types';
import { ArrowDown, ArrowUp, Plus } from 'lucide-react';

const TIME_OFF_CONFIG: Record<TimeOffType, { label: string; defaultHours: number; placeholder: string }> = {
  SICK_DAY: { label: 'Sick Day', defaultHours: 8, placeholder: 'Sick leave reason' },
  PTO: { label: 'Paid Time Off (PTO)', defaultHours: 8, placeholder: 'PTO reason' },
  HALF_DAY: { label: 'Half Day Leave', defaultHours: 4, placeholder: 'Half-day leave reason' },
  HOURLY_PERMISSION: { label: 'Hourly Permission', defaultHours: 2, placeholder: 'Reason for hourly permission' },
  OTHER_LEAVE: { label: 'Other Leave', defaultHours: 8, placeholder: 'Leave details' },
};

export const TimeOffPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const deepLinkEntryId = Number(searchParams.get('entryId') || 0) || null;
  const deepLinkDate = searchParams.get('date') || '';

  const [editingId, setEditingId] = useState<number | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'ALL' | TimeOffStatus>('ALL');
  const [leaveTypeFilter, setLeaveTypeFilter] = useState<'ALL' | TimeOffType>('ALL');
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState<'request_date' | 'created_at' | 'hours' | 'status'>('request_date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [startDate, setStartDate] = useState(deepLinkDate || '');
  const [endDate, setEndDate] = useState(deepLinkDate || '');

  const [formData, setFormData] = useState({
    start_date: new Date().toISOString().split('T')[0],
    end_date: new Date().toISOString().split('T')[0],
    hours: 8,
    reason: '',
    leave_type: 'PTO' as TimeOffType,
  });

  const [editData, setEditData] = useState<{
    request_date: string;
    hours: number;
    reason: string;
    leave_type: TimeOffType;
  } | null>(null);

  const queryParams = useMemo(
    () => ({
      status: statusFilter === 'ALL' ? undefined : statusFilter,
      leave_type: leaveTypeFilter === 'ALL' ? undefined : leaveTypeFilter,
      search: search.trim() || undefined,
      sort_by: sortBy,
      sort_order: sortOrder,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      limit: 500,
    }),
    [statusFilter, leaveTypeFilter, search, sortBy, sortOrder, startDate, endDate]
  );

  const { data: requests, isLoading, error } = useTimeOffRequests(queryParams);

  const searchSuggestions = useMemo(() => {
    const set = new Set<string>();
    Object.values(TIME_OFF_CONFIG).forEach((c) => set.add(c.label));
    (requests ?? []).forEach((r: TimeOffRequest) => { if (r.reason) set.add(r.reason); });
    return Array.from(set).filter(Boolean).sort();
  }, [requests]);
  const createMutation = useCreateTimeOffRequest();
  const submitMutation = useSubmitTimeOffRequests();
  const updateMutation = useUpdateTimeOffRequest(editingId || 0);
  const deleteMutation = useDeleteTimeOffRequest();

  useEffect(() => {
    if (!deepLinkEntryId || !requests || requests.length === 0) return;
    const target = document.getElementById(`time-off-${deepLinkEntryId}`);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [deepLinkEntryId, requests]);

  if (isLoading && !requests) return <Loading />;
  if (error) return <Error message="Failed to load time off requests" />;

  const timeOffEntries = requests || [];
  const draftEntries = timeOffEntries.filter((entry: TimeOffRequest) => entry.status === 'DRAFT');
  const submittedEntries = timeOffEntries.filter((entry: TimeOffRequest) => entry.status === 'SUBMITTED');
  const approvedEntries = timeOffEntries.filter((entry: TimeOffRequest) => entry.status === 'APPROVED');
  const rejectedEntries = timeOffEntries.filter((entry: TimeOffRequest) => entry.status === 'REJECTED');

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();

    try {
      const start = new Date(formData.start_date + 'T00:00:00');
      const end = new Date(formData.end_date + 'T00:00:00');
      const dates: string[] = [];
      const cursor = new Date(start);
      while (cursor <= end) {
        dates.push(cursor.toISOString().split('T')[0]);
        cursor.setDate(cursor.getDate() + 1);
      }
      for (const request_date of dates) {
        await createMutation.mutateAsync({ request_date, hours: formData.hours, reason: formData.reason, leave_type: formData.leave_type });
      }
      setShowForm(false);
      setFormData({
        start_date: new Date().toISOString().split('T')[0],
        end_date: new Date().toISOString().split('T')[0],
        hours: 8,
        reason: '',
        leave_type: 'PTO',
      });
    } catch (createError) {
      console.error('Failed to create time off request', createError);
    }
  };

  const handleSubmitSingle = async (id: number) => {
    try {
      await submitMutation.mutateAsync([id]);
    } catch (submitError) {
      console.error('Failed to submit time off request', submitError);
    }
  };

  const handleEdit = (entry: TimeOffRequest) => {
    setEditingId(entry.id);
    setEditData({
      request_date: entry.request_date,
      hours: typeof entry.hours === 'string' ? parseFloat(entry.hours) : entry.hours,
      reason: entry.reason,
      leave_type: entry.leave_type,
    });
  };

  const handleSaveEdit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingId || !editData) return;

    try {
      await updateMutation.mutateAsync(editData);
      setEditingId(null);
      setEditData(null);
    } catch (updateError) {
      console.error('Failed to update request', updateError);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this time off request?')) return;
    try {
      await deleteMutation.mutateAsync(id);
      setEditingId(null);
      setEditData(null);
    } catch (deleteError) {
      console.error('Failed to delete request', deleteError);
    }
  };

  const renderRequestCard = (entry: TimeOffRequest, showActions: boolean) => {
    const isHighlighted = entry.id === deepLinkEntryId;
    return (
      <div
        id={`time-off-${entry.id}`}
        key={entry.id}
        className={`border rounded p-4 bg-card ${isHighlighted ? 'ring-2 ring-primary border-primary' : ''}`}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="font-medium">{entry.request_date}</p>
            <p className="text-sm text-muted-foreground">{TIME_OFF_CONFIG[entry.leave_type].label}</p>
            <p className="text-sm mt-2">{entry.reason}</p>
            <p className="text-sm font-medium mt-1">{entry.hours} hours</p>
            {entry.rejection_reason && (
              <div className="bg-red-50 border border-red-200 p-2 rounded text-sm mt-2">
                <p className="font-medium text-red-900">Rejection reason:</p>
                <p className="text-red-800">{entry.rejection_reason}</p>
              </div>
            )}
          </div>
          <div className="flex flex-col items-end gap-2 shrink-0">
            <span className="px-2 py-1 rounded text-xs font-medium bg-slate-100 text-slate-600">{entry.status}</span>
            {showActions && entry.status === 'DRAFT' && (
              <div className="flex flex-col gap-1 w-24">
                <button
                  onClick={() => handleSubmitSingle(entry.id)}
                  className="w-full px-3 py-1.5 bg-primary text-primary-foreground text-xs rounded hover:bg-primary/80"
                >
                  Submit
                </button>
                <button
                  onClick={() => handleEdit(entry)}
                  className="w-full px-3 py-1.5 bg-slate-100 text-slate-700 text-xs rounded hover:bg-slate-200"
                >
                  Edit
                </button>
                <button
                  onClick={() => handleDelete(entry.id)}
                  className="w-full px-3 py-1.5 bg-destructive/10 text-destructive text-xs rounded hover:bg-destructive/20"
                >
                  Delete
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div>
      <div>
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-3xl font-bold">Time Off</h1>
          <button
            onClick={() => setShowForm((value) => !value)}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90"
          >
            <Plus className="w-4 h-4" />
            New Time Off Request
          </button>
        </div>

        <div className="bg-card border rounded-lg p-4 mb-4 grid grid-cols-1 md:grid-cols-4 gap-3">
          <SearchInput
            value={search}
            onChange={setSearch}
            suggestions={searchSuggestions}
            placeholder="Search reason/type"
            className="px-3 py-2 border rounded w-full"
          />
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as 'ALL' | TimeOffStatus)}
            className="px-3 py-2 border rounded"
          >
            <option value="ALL">All Status</option>
            <option value="DRAFT">Draft</option>
            <option value="SUBMITTED">Submitted</option>
            <option value="APPROVED">Approved</option>
            <option value="REJECTED">Rejected</option>
          </select>
          <select
            value={leaveTypeFilter}
            onChange={(event) => setLeaveTypeFilter(event.target.value as 'ALL' | TimeOffType)}
            className="px-3 py-2 border rounded"
          >
            <option value="ALL">All Types</option>
            {Object.keys(TIME_OFF_CONFIG).map((type) => (
              <option key={type} value={type}>
                {TIME_OFF_CONFIG[type as TimeOffType].label}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-full px-3 py-2 border rounded" />
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="w-full px-3 py-2 border rounded" />
          </div>
        </div>

        <div className="mb-6 flex items-center justify-end gap-2">
          <select
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value as 'request_date' | 'created_at' | 'hours' | 'status')}
            className="h-9 w-40 rounded border bg-card px-2 text-xs"
          >
            <option value="request_date">Request Date</option>
            <option value="created_at">Created</option>
            <option value="hours">Hours</option>
            <option value="status">Status</option>
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

        {showForm && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-xl font-bold mb-4">Create Time Off Request</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Type</label>
                  <select
                    value={formData.leave_type}
                    onChange={(e) => {
                      const leave_type = e.target.value as TimeOffType;
                      setFormData((prev) => ({
                        ...prev,
                        leave_type,
                        hours: TIME_OFF_CONFIG[leave_type].defaultHours,
                        reason: prev.reason || TIME_OFF_CONFIG[leave_type].placeholder,
                      }));
                    }}
                    className="w-full px-3 py-2 border rounded"
                    required
                  >
                    {Object.entries(TIME_OFF_CONFIG).map(([value, config]) => (
                      <option key={value} value={value}>
                        {config.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Start Date</label>
                  <input
                    type="date"
                    value={formData.start_date}
                    onChange={(e) => {
                      const val = e.target.value;
                      setFormData((prev) => ({ ...prev, start_date: val, end_date: prev.end_date < val ? val : prev.end_date }));
                    }}
                    className="w-full px-3 py-2 border rounded"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">End Date</label>
                  <input
                    type="date"
                    value={formData.end_date}
                    min={formData.start_date}
                    onChange={(e) => setFormData({ ...formData, end_date: e.target.value })}
                    className="w-full px-3 py-2 border rounded"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Hours</label>
                  <input
                    type="number"
                    step="0.5"
                    min="0.5"
                    max="8"
                    value={formData.hours}
                    onChange={(e) => setFormData({ ...formData, hours: parseFloat(e.target.value) })}
                    className="w-full px-3 py-2 border rounded"
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Reason</label>
                <textarea
                  value={formData.reason}
                  onChange={(e) => setFormData({ ...formData, reason: e.target.value })}
                  placeholder={TIME_OFF_CONFIG[formData.leave_type].placeholder}
                  className="w-full px-3 py-2 border rounded"
                  rows={3}
                  required
                />
              </div>

              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={createMutation.isPending}
                  className="flex-1 px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
                >
                  {createMutation.isPending ? 'Creating...' : 'Create Request'}
                </button>
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="flex-1 px-4 py-2 bg-muted text-muted-foreground rounded hover:bg-muted/90"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        )}

        {editingId && editData && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-xl font-bold mb-4">Edit Time Off Request</h2>
            <form onSubmit={handleSaveEdit} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Type</label>
                  <select
                    value={editData.leave_type}
                    onChange={(e) =>
                      setEditData((prev) =>
                        prev
                          ? {
                              ...prev,
                              leave_type: e.target.value as TimeOffType,
                            }
                          : prev
                      )
                    }
                    className="w-full px-3 py-2 border rounded"
                    required
                  >
                    {Object.entries(TIME_OFF_CONFIG).map(([value, config]) => (
                      <option key={value} value={value}>
                        {config.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Date</label>
                  <input
                    type="date"
                    value={editData.request_date}
                    onChange={(e) => setEditData((prev) => (prev ? { ...prev, request_date: e.target.value } : prev))}
                    className="w-full px-3 py-2 border rounded"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Hours</label>
                  <input
                    type="number"
                    step="0.5"
                    min="0.5"
                    max="8"
                    value={editData.hours}
                    onChange={(e) => setEditData((prev) => (prev ? { ...prev, hours: parseFloat(e.target.value) } : prev))}
                    className="w-full px-3 py-2 border rounded"
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Reason</label>
                <textarea
                  value={editData.reason}
                  onChange={(e) => setEditData((prev) => (prev ? { ...prev, reason: e.target.value } : prev))}
                  className="w-full px-3 py-2 border rounded"
                  rows={3}
                  required
                />
              </div>

              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={updateMutation.isPending}
                  className="flex-1 px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50"
                >
                  {updateMutation.isPending ? 'Saving...' : 'Save Draft'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditingId(null);
                    setEditData(null);
                  }}
                  className="flex-1 px-4 py-2 bg-muted text-muted-foreground rounded hover:bg-muted/90"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        )}

        {draftEntries.length > 0 && (
          <div className="mb-8">
            <h2 className="text-xl font-bold mb-4">Draft Requests</h2>
            <div className="space-y-4 mb-4">{draftEntries.map((entry) => renderRequestCard(entry, true))}</div>
          </div>
        )}

        {submittedEntries.length > 0 && (
          <div className="mb-8">
            <h2 className="text-xl font-bold mb-4">Submitted Requests</h2>
            <div className="space-y-4">{submittedEntries.map((entry) => renderRequestCard(entry, false))}</div>
          </div>
        )}

        {approvedEntries.length > 0 && (
          <div className="mb-8">
            <h2 className="text-xl font-bold mb-4 text-emerald-700">Approved Requests</h2>
            <div className="space-y-4">{approvedEntries.map((entry) => renderRequestCard(entry, false))}</div>
          </div>
        )}

        {rejectedEntries.length > 0 && (
          <div className="mb-8">
            <h2 className="text-xl font-bold mb-4 text-red-700">Rejected Requests</h2>
            <div className="space-y-4">{rejectedEntries.map((entry) => renderRequestCard(entry, false))}</div>
          </div>
        )}

        {!isLoading && timeOffEntries.length === 0 && <EmptyState message="No time off requests yet." />}
      </div>
    </div>
  );
};
