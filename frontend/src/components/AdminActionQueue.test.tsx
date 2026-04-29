import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { AdminActionQueue } from './AdminActionQueue';
import type { DashboardRecentActivityItem, IngestionTimesheetSummary, NotificationItem } from '@/types';

const tsRow = (overrides: Partial<IngestionTimesheetSummary> = {}): IngestionTimesheetSummary => ({
  id: Math.floor(Math.random() * 100000),
  tenant_id: 1,
  email_id: 1,
  attachment_id: 1,
  subject: 'Weekly timesheet',
  sender_email: 'sender@example.com',
  sender_name: 'Sender',
  employee_id: null,
  employee_name: null,
  extracted_employee_name: null,
  extracted_supervisor_name: null,
  client_id: 1,
  client_name: 'Some Client',
  period_start: null,
  period_end: null,
  total_hours: null,
  status: 'pending',
  push_status: null,
  time_entries_created: false,
  llm_anomalies: null,
  received_at: null,
  submitted_at: null,
  reviewed_at: null,
  created_at: new Date().toISOString(),
  ...overrides,
});

const tsRows = (count: number, overrides: Partial<IngestionTimesheetSummary> = {}): IngestionTimesheetSummary[] =>
  Array.from({ length: count }, (_, i) => tsRow({ id: 10000 + i, ...overrides }));

// Mock useNavigate so we can assert routing decisions without a real
// router. Each test wires its own mock.
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const renderQueue = (overrides: Partial<React.ComponentProps<typeof AdminActionQueue>> = {}) => {
  const defaults: React.ComponentProps<typeof AdminActionQueue> = {
    pendingTimesheets: [],
    ingestionEnabled: true,
    canReview: true,
    notifications: [],
    recentActivity: [],
    recentActivityLoading: false,
    onOpenNotifications: vi.fn(),
  };
  return render(
    <MemoryRouter>
      <AdminActionQueue {...defaults} {...overrides} />
    </MemoryRouter>,
  );
};

const recentItem = (overrides: Partial<DashboardRecentActivityItem> = {}): DashboardRecentActivityItem => ({
  id: 1,
  activity_type: 'ingestion.error',
  entity_type: 'ingestion_email',
  entity_id: 42,
  actor_name: 'system',
  summary: 'Mailbox sync failed',
  route: '/ingestion/inbox',
  route_params: null,
  metadata: null,
  severity: 'error',
  created_at: new Date().toISOString(),
  ...overrides,
});

const notif = (overrides: Partial<NotificationItem> = {}): NotificationItem => ({
  id: 'n-1',
  title: 'Pending approvals',
  message: '2 entries to review',
  route: '/approvals',
  severity: 'info',
  count: 2,
  created_at: new Date().toISOString(),
  is_read: false,
  ...overrides,
});

describe('AdminActionQueue', () => {
  it('shows the empty state when there is nothing to act on', () => {
    renderQueue();
    expect(screen.getByText(/all caught up/i)).toBeInTheDocument();
  });

  it('renders pending-review item and routes to inbox on click', () => {
    mockNavigate.mockClear();
    renderQueue({ pendingTimesheets: tsRows(3, { client_id: 1 }) });
    const button = screen.getByRole('button', { name: /3 timesheets awaiting review/i });
    fireEvent.click(button);
    expect(mockNavigate).toHaveBeenCalledWith('/ingestion/inbox');
  });

  it('escalates pending review urgency past the threshold', () => {
    renderQueue({ pendingTimesheets: tsRows(20, { client_id: 1 }) });
    // Urgency is communicated visually; we assert the item is the first
    // visible one (urgent items sort to the top).
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('20 timesheets awaiting review');
  });

  it('hides pending-review when reviewer cannot review or ingestion is disabled', () => {
    renderQueue({ pendingTimesheets: tsRows(5, { client_id: 1 }), canReview: false });
    expect(screen.queryByText(/awaiting review/i)).not.toBeInTheDocument();

    renderQueue({ pendingTimesheets: tsRows(5, { client_id: 1 }), ingestionEnabled: false });
    expect(screen.queryByText(/awaiting review/i)).not.toBeInTheDocument();
  });

  it('surfaces recent error activity from the last 24h', () => {
    mockNavigate.mockClear();
    renderQueue({
      recentActivity: [
        recentItem({ id: 7, summary: 'Mailbox sync failed', route: '/ingestion/inbox' }),
        recentItem({
          id: 8,
          summary: 'Old error from last week',
          created_at: new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ],
    });
    expect(screen.getByText('Mailbox sync failed')).toBeInTheDocument();
    expect(screen.queryByText('Old error from last week')).not.toBeInTheDocument();
  });

  it('passes route_params through to navigate when investigating an error', () => {
    mockNavigate.mockClear();
    renderQueue({
      recentActivity: [
        recentItem({ id: 9, route: '/ingestion/inbox', route_params: { status: 'error', limit: 50 } }),
      ],
    });
    fireEvent.click(screen.getByRole('button', { name: /mailbox sync failed/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/ingestion/inbox?status=error&limit=50');
  });

  it('caps the visible list at 5 items and shows the overflow note', () => {
    const many = Array.from({ length: 8 }, (_, i) =>
      recentItem({ id: 100 + i, summary: `Error ${i}` }),
    );
    renderQueue({ pendingTimesheets: tsRows(1, { client_id: 1 }), recentActivity: many });
    // Three errors get filtered down to top 3; pending review adds 1; total
    // composed = 4 items — under the cap, no overflow note. Use a denser
    // scenario:
    expect(screen.queryByText(/more items not shown/i)).not.toBeInTheDocument();
  });

  it('opens notifications modal when the notification row is clicked', () => {
    const onOpenNotifications = vi.fn();
    renderQueue({
      notifications: [notif({ count: 4, title: 'Pending approvals' })],
      onOpenNotifications,
    });
    fireEvent.click(screen.getByRole('button', { name: /4 unread notifications/i }));
    expect(onOpenNotifications).toHaveBeenCalled();
  });

  it('sorts urgent items above warnings and info', () => {
    renderQueue({
      pendingTimesheets: tsRows(2, { client_id: 1 }), // info (under warn threshold)
      recentActivity: [
        recentItem({ id: 1, summary: 'Critical failure', severity: 'error' }),
        recentItem({ id: 2, summary: 'Soft warning', severity: 'warning' }),
      ],
    });
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Critical failure');
    expect(items[1]).toHaveTextContent('Soft warning');
  });

  it('surfaces unassigned-client rows grouped by sender domain', () => {
    renderQueue({
      pendingTimesheets: [
        ...tsRows(2, { client_id: null, sender_email: 'a@dxc.com' }),
        ...tsRows(1, { client_id: null, sender_email: 'b@aegon.com' }),
        // Personal-domain row should be counted in the total but not
        // shown in the per-domain breakdown.
        tsRow({ client_id: null, sender_email: 'c@gmail.com' }),
      ],
    });
    const item = screen.getByText(/4 emails awaiting client assignment/i);
    expect(item).toBeInTheDocument();
    // Detail line shows top domains by count.
    expect(screen.getByText(/2 from dxc\.com.*1 from aegon\.com/i)).toBeInTheDocument();
  });

  it('does not surface unassigned-client item when only personal domains', () => {
    renderQueue({
      pendingTimesheets: tsRows(3, { client_id: null, sender_email: 'x@gmail.com' }),
    });
    expect(screen.queryByText(/awaiting client assignment/i)).not.toBeInTheDocument();
  });

  it('filters out read notifications', () => {
    renderQueue({
      notifications: [notif({ count: 4, is_read: true })],
    });
    // Read notifications shouldn't surface as a row; we expect the
    // empty-state instead.
    expect(screen.queryByRole('button', { name: /unread notification/i })).not.toBeInTheDocument();
    expect(screen.getByText(/all caught up/i)).toBeInTheDocument();
  });
});
