import React, { useState } from 'react';
import { format, parseISO } from 'date-fns';
import { Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { Loading } from '@/components';
import { useAuditTrail } from '@/hooks';
import type { DashboardRecentActivityItem } from '@/types';

const ACTIVITY_TYPES = [
  { value: '', label: 'All types' },
  { value: 'TIME_ENTRY_APPROVED', label: 'Time Entry Approved' },
  { value: 'TIME_ENTRY_REJECTED', label: 'Time Entry Rejected' },
  { value: 'TIME_ENTRIES_BATCH_APPROVED', label: 'Batch Approved' },
  { value: 'TIME_ENTRIES_BATCH_REJECTED', label: 'Batch Rejected' },
  { value: 'TIME_OFF_APPROVED', label: 'Time Off Approved' },
  { value: 'TIME_OFF_REJECTED', label: 'Time Off Rejected' },
  { value: 'USER_CREATED', label: 'User Created' },
  { value: 'USER_UPDATED', label: 'User Updated' },
  { value: 'USER_DELETED', label: 'User Deleted' },
];

const PAGE_SIZE = 50;

const getSeverityClasses = (severity: string) => {
  if (severity === 'error') return 'bg-red-500/15 text-red-600';
  if (severity === 'warning') return 'bg-amber-500/15 text-amber-600';
  if (severity === 'success') return 'bg-emerald-500/15 text-emerald-600';
  return 'bg-sky-500/15 text-sky-600';
};

export const AuditTrailPage: React.FC = () => {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [activityType, setActivityType] = useState('');
  const [page, setPage] = useState(0);

  const { data: items = [], isLoading } = useAuditTrail({
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    activity_type: activityType || undefined,
    search: search.trim() || undefined,
  });

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Audit Trail</h1>
        <p className="text-sm text-muted-foreground mt-1">Activity log of all actions across the organization.</p>
      </div>

      <div className="bg-card border rounded-lg p-4 mb-4 flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0); }}
            placeholder="Search activity..."
            className="field-input pl-10"
          />
        </div>
        <select
          value={activityType}
          onChange={(e) => { setActivityType(e.target.value); setPage(0); }}
          className="field-input w-auto min-w-[180px]"
        >
          {ACTIVITY_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <Loading message="Loading audit trail..." />
      ) : items.length === 0 ? (
        <div className="bg-card border rounded-lg p-12 text-center text-muted-foreground">
          No activity found.
        </div>
      ) : (
        <>
          <div className="bg-card border rounded-lg overflow-hidden">
            <table className="min-w-full text-left">
              <thead className="border-b border-border">
                <tr className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                  <th className="px-4 py-3 font-medium">Time</th>
                  <th className="px-4 py-3 font-medium">User</th>
                  <th className="px-4 py-3 font-medium">Action</th>
                  <th className="px-4 py-3 font-medium">Summary</th>
                  <th className="px-4 py-3 font-medium">Severity</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item: DashboardRecentActivityItem) => (
                  <tr
                    key={item.id}
                    className="border-b border-border/50 hover:bg-muted/30 transition cursor-pointer"
                    onClick={() => item.route && navigate(item.route)}
                  >
                    <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap">
                      {format(parseISO(item.created_at), 'MMM d, yyyy h:mm a')}
                    </td>
                    <td className="px-4 py-3 text-sm font-medium text-foreground whitespace-nowrap">
                      {item.actor_name || '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap">
                      {item.activity_type.replace(/_/g, ' ')}
                    </td>
                    <td className="px-4 py-3 text-sm text-foreground">
                      {item.summary}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${getSeverityClasses(item.severity)}`}>
                        {item.severity}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between mt-4">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="action-button-secondary text-sm disabled:opacity-50"
            >
              Previous
            </button>
            <span className="text-xs text-muted-foreground">Page {page + 1}</span>
            <button
              type="button"
              onClick={() => setPage((p) => p + 1)}
              disabled={items.length < PAGE_SIZE}
              className="action-button-secondary text-sm disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
};
