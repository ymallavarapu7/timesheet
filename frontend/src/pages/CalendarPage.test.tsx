import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CalendarPage } from './CalendarPage';
import type { TimeEntry, TimeOffRequest } from '@/types';

const mocks = vi.hoisted(() => ({
  useTimeEntries: vi.fn(),
  useTimeOffRequests: vi.fn(),
  useUpdateTimeEntry: vi.fn(),
  useUpdateTimeOffRequest: vi.fn(),
}));

vi.mock('@/hooks', () => ({
  useTimeEntries: mocks.useTimeEntries,
  useTimeOffRequests: mocks.useTimeOffRequests,
  useUpdateTimeEntry: mocks.useUpdateTimeEntry,
  useUpdateTimeOffRequest: mocks.useUpdateTimeOffRequest,
}));

vi.mock('@/components', () => ({
  Header: () => <div>Header</div>,
  Loading: () => <div>Loading</div>,
  Error: ({ message }: { message: string }) => <div>{message}</div>,
  EmptyState: ({ message }: { message: string }) => <div>{message}</div>,
}));

describe('CalendarPage', () => {
  beforeEach(() => {
    const timeEntries: TimeEntry[] = [
      {
        id: 8001,
        user_id: 11,
        project_id: 101,
        task_id: null,
        entry_date: '2026-03-16',
        hours: '8',
        description: 'Worked on project tasks',
        is_billable: true,
        status: 'APPROVED',
        submitted_at: '2026-03-16T12:00:00Z',
        approved_by: 2,
        approved_at: '2026-03-16T15:00:00Z',
        rejection_reason: null,
        quickbooks_time_activity_id: null,
        created_at: '2026-03-16T08:00:00Z',
        updated_at: '2026-03-16T15:00:00Z',
      },
    ];
    const timeOffEntries: TimeOffRequest[] = [];

    mocks.useTimeEntries.mockReturnValue({ data: timeEntries, isLoading: false, error: null });
    mocks.useTimeOffRequests.mockReturnValue({ data: timeOffEntries, isLoading: false, error: null });
    mocks.useUpdateTimeEntry.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    mocks.useUpdateTimeOffRequest.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  });

  it('renders calendar portal with month view and legend entries', () => {
    render(
      <MemoryRouter>
        <CalendarPage />
      </MemoryRouter>
    );

    expect(screen.getByText('Calendar')).toBeInTheDocument();
    expect(screen.getByText('Mon')).toBeInTheDocument();
    expect(screen.getByText('Tue')).toBeInTheDocument();
  });
});
