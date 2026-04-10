import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApprovalsPage } from './ApprovalsPage';
import type { TimeEntry } from '@/types';

const mocks = vi.hoisted(() => ({
  usePendingApprovals: vi.fn(),
  useApprovalHistory: vi.fn(),
  useApproveTimeEntryBatch: vi.fn(),
  useRejectTimeEntryBatch: vi.fn(),
}));

vi.mock('@/hooks', () => ({
  usePendingApprovals: mocks.usePendingApprovals,
  useApprovalHistory: mocks.useApprovalHistory,
  useApproveTimeEntryBatch: mocks.useApproveTimeEntryBatch,
  useRejectTimeEntryBatch: mocks.useRejectTimeEntryBatch,
}));

vi.mock('@/components', () => ({
  Header: () => <div>Header</div>,
  Loading: () => <div>Loading</div>,
  Error: ({ message }: { message: string }) => <div>{message}</div>,
  EmptyState: ({ message }: { message: string }) => <div>{message}</div>,
  SearchInput: ({ value, onChange, placeholder, className }: { value: string; onChange: (v: string) => void; placeholder?: string; className?: string }) => (
    <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={className} />
  ),
}));

describe('ApprovalsPage', () => {
  beforeEach(() => {
    const pending: TimeEntry[] = [
      {
        id: 7001,
        user_id: 22,
        project_id: 101,
        task_id: null,
        entry_date: '2026-03-16',
        hours: '8',
        description: 'Pending approval',
        is_billable: true,
        status: 'SUBMITTED',
        submitted_at: '2026-03-16T12:00:00Z',
        approved_by: null,
        approved_at: null,
        rejection_reason: null,
        quickbooks_time_activity_id: null,
        created_at: '2026-03-16T08:00:00Z',
        updated_at: '2026-03-16T12:00:00Z',
        user: {
          id: 22,
          email: 'employee@example.com',
          username: 'employee',
          full_name: 'Employee One',
          title: 'Engineer',
          department: 'Engineering',
          role: 'EMPLOYEE',
          is_active: true,
          has_changed_password: true, email_verified: true, tenant_id: 1,
          manager_id: 2,
          project_ids: [101],
          created_at: '2026-03-01T00:00:00Z',
          updated_at: '2026-03-01T00:00:00Z',
        },
      },
    ];

    mocks.usePendingApprovals.mockReturnValue({ data: pending, isLoading: false, error: null });
    mocks.useApprovalHistory.mockReturnValue({ data: [], isLoading: false, error: null });
    mocks.useApproveTimeEntryBatch.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    mocks.useRejectTimeEntryBatch.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  });

  it('renders pending approvals view', () => {
    render(
      <MemoryRouter>
        <ApprovalsPage />
      </MemoryRouter>
    );

    expect(screen.getByText('Pending Approvals')).toBeInTheDocument();
    expect(screen.getByText('Filter by employee')).toBeInTheDocument();
  });

  it('groups same-week entries into a single approval card', () => {
    const pending: TimeEntry[] = [
      {
        id: 7001,
        user_id: 22,
        project_id: 101,
        task_id: null,
        entry_date: '2026-03-09',
        hours: '8',
        description: 'Monday work',
        is_billable: true,
        status: 'SUBMITTED',
        submitted_at: '2026-03-10T12:00:00Z',
        approved_by: null,
        approved_at: null,
        rejection_reason: null,
        quickbooks_time_activity_id: null,
        created_at: '2026-03-09T08:00:00Z',
        updated_at: '2026-03-10T12:00:00Z',
        user: {
          id: 22,
          email: 'employee@example.com',
          username: 'employee',
          full_name: 'Employee One',
          title: 'Engineer',
          department: 'Engineering',
          role: 'EMPLOYEE',
          is_active: true,
          has_changed_password: true, email_verified: true,
          tenant_id: 1,
          manager_id: 2,
          project_ids: [101],
          created_at: '2026-03-01T00:00:00Z',
          updated_at: '2026-03-01T00:00:00Z',
        },
      },
      {
        id: 7002,
        user_id: 22,
        project_id: 101,
        task_id: null,
        entry_date: '2026-03-10',
        hours: '8',
        description: 'Tuesday work',
        is_billable: true,
        status: 'SUBMITTED',
        submitted_at: '2026-03-10T12:00:00Z',
        approved_by: null,
        approved_at: null,
        rejection_reason: null,
        quickbooks_time_activity_id: null,
        created_at: '2026-03-10T08:00:00Z',
        updated_at: '2026-03-10T12:00:00Z',
        user: {
          id: 22,
          email: 'employee@example.com',
          username: 'employee',
          full_name: 'Employee One',
          title: 'Engineer',
          department: 'Engineering',
          role: 'EMPLOYEE',
          is_active: true,
          has_changed_password: true, email_verified: true,
          tenant_id: 1,
          manager_id: 2,
          project_ids: [101],
          created_at: '2026-03-01T00:00:00Z',
          updated_at: '2026-03-01T00:00:00Z',
        },
      },
    ];

    mocks.usePendingApprovals.mockReturnValue({ data: pending, isLoading: false, error: null });

    render(
      <MemoryRouter>
        <ApprovalsPage />
      </MemoryRouter>
    );

    expect(screen.getByText(/2 submitted entries/i)).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Approve Week' })).toHaveLength(1);
  });
});
