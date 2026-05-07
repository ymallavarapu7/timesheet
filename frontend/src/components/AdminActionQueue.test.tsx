import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { AdminActionQueue } from './AdminActionQueue';
import type { DashboardRecentActivityItem, NotificationItem, User, UserRole } from '@/types';

const userRow = (overrides: Partial<User> = {}): User => ({
  id: Math.floor(Math.random() * 100000),
  email: 'someone@example.com',
  username: 'someone',
  full_name: 'Some One',
  role: 'EMPLOYEE' as UserRole,
  is_active: true,
  email_verified: true,
  has_changed_password: true,
  manager_id: 99,
  tenant_id: 1,
  timezone: 'UTC',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  ...overrides,
});

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('@/hooks', () => ({
  useDismissedAttentionSignals: () => ({ data: [] }),
  useDismissAttentionSignal: () => ({ mutate: vi.fn() }),
}));

const renderQueue = (overrides: Partial<React.ComponentProps<typeof AdminActionQueue>> = {}) => {
  const defaults: React.ComponentProps<typeof AdminActionQueue> = {
    users: [],
    notifications: [],
    recentActivity: [],
    recentActivityLoading: false,
    currentUserId: null,
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
  actor_id: null,
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
  title: 'Heads up',
  message: 'Something happened',
  route: '/admin',
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

  it('flags active employees and managers without a manager_id', () => {
    mockNavigate.mockClear();
    renderQueue({
      users: [
        userRow({ id: 1, full_name: 'Bob Employee', role: 'EMPLOYEE', manager_id: null }),
        userRow({ id: 2, full_name: 'Alice Manager', role: 'MANAGER', manager_id: null }),
        // Inactive: skipped.
        userRow({ id: 3, full_name: 'Inactive Bob', role: 'EMPLOYEE', manager_id: null, is_active: false }),
        // ADMIN/VIEWER/PLATFORM_ADMIN can legitimately have no manager.
        userRow({ id: 4, full_name: 'Admin Person', role: 'ADMIN', manager_id: null }),
        userRow({ id: 5, full_name: 'Viewer Person', role: 'VIEWER', manager_id: null }),
        userRow({ id: 6, full_name: 'Platform Admin', role: 'PLATFORM_ADMIN', manager_id: null }),
      ],
    });
    const button = screen.getByRole('button', { name: /2 users without a manager/i });
    fireEvent.click(button);
    expect(mockNavigate).toHaveBeenCalledWith('/user-management?status=NO_MANAGER');
  });

  it('flags stale unverified invitations older than 7 days', () => {
    mockNavigate.mockClear();
    const oldIso = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString();
    const recentIso = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString();
    renderQueue({
      users: [
        userRow({ id: 1, email_verified: false, created_at: oldIso }),
        userRow({ id: 2, email_verified: false, created_at: recentIso }), // < 7d, ignored
        userRow({ id: 3, email_verified: true, created_at: oldIso }),     // verified, ignored
      ],
    });
    const button = screen.getByRole('button', { name: /1 unverified invitation/i });
    fireEvent.click(button);
    expect(mockNavigate).toHaveBeenCalledWith('/user-management?verified=NO');
  });

  it('surfaces recent error activity from the last 24h only', () => {
    mockNavigate.mockClear();
    renderQueue({
      recentActivity: [
        recentItem({ id: 7, summary: 'Mailbox sync failed' }),
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

  it('opens notifications modal when the notification row is clicked', () => {
    const onOpenNotifications = vi.fn();
    renderQueue({
      notifications: [notif({ count: 4, title: 'Heads up' })],
      onOpenNotifications,
    });
    fireEvent.click(screen.getByRole('button', { name: /4 unread notifications/i }));
    expect(onOpenNotifications).toHaveBeenCalled();
  });

  it('sorts urgent items above warnings and info', () => {
    const oldIso = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString();
    renderQueue({
      // Urgent: user without manager.
      users: [
        userRow({ id: 1, full_name: 'Org Gap', role: 'EMPLOYEE', manager_id: null }),
        // Warn: stale unverified invitation.
        userRow({ id: 2, full_name: 'Stale Invite', email_verified: false, created_at: oldIso }),
      ],
      // Info: notifications.
      notifications: [notif({ count: 1 })],
    });
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent(/without a manager/i);
    expect(items[1]).toHaveTextContent(/unverified invitation/i);
    expect(items[items.length - 1]).toHaveTextContent(/unread notification/i);
  });

  it('filters out read notifications', () => {
    renderQueue({
      notifications: [notif({ count: 4, is_read: true })],
    });
    expect(screen.queryByRole('button', { name: /unread notification/i })).not.toBeInTheDocument();
    expect(screen.getByText(/all caught up/i)).toBeInTheDocument();
  });
});
