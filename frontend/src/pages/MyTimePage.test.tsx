import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { addDays, format, startOfWeek } from 'date-fns';

import { MyTimePage } from './MyTimePage';
import type { NotificationSummary, Project, Task, TimeEntry, User } from '@/types';

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  useTimeEntries: vi.fn(),
  useCreateTimeEntry: vi.fn(),
  useSubmitTimeEntries: vi.fn(),
  useProjects: vi.fn(),
  useTasks: vi.fn(),
  useUpdateTimeEntry: vi.fn(),
  useNotifications: vi.fn(),
  useWeeklySubmitStatus: vi.fn(),
  useCreateTask: vi.fn(),
  useMarkNotificationRead: vi.fn(),
}));

vi.mock('@/hooks', () => ({
  useAuth: mocks.useAuth,
  useTimeEntries: mocks.useTimeEntries,
  useCreateTimeEntry: mocks.useCreateTimeEntry,
  useSubmitTimeEntries: mocks.useSubmitTimeEntries,
  useProjects: mocks.useProjects,
  useTasks: mocks.useTasks,
  useUpdateTimeEntry: mocks.useUpdateTimeEntry,
  useNotifications: mocks.useNotifications,
  useWeeklySubmitStatus: mocks.useWeeklySubmitStatus,
  useCreateTask: mocks.useCreateTask,
  useMarkNotificationRead: mocks.useMarkNotificationRead,
}));

vi.mock('@/components', () => ({
  Header: () => <div>Header</div>,
  Loading: () => <div>Loading</div>,
  Error: ({ message }: { message: string }) => <div>{message}</div>,
  EmptyState: ({ message }: { message: string }) => <div>{message}</div>,
  TimeEntryRow: () => <div>TimeEntryRow</div>,
  SearchInput: ({ value, onChange, placeholder, className }: { value: string; onChange: (v: string) => void; placeholder?: string; className?: string }) => (
    <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={className} />
  ),
  DateRangePickerCalendar: ({ startDate, endDate, onStartDateChange, onEndDateChange }: { startDate: string; endDate: string; onStartDateChange: (v: string) => void; onEndDateChange: (v: string) => void }) => (
    <div>
      <input
        type="date"
        value={startDate}
        onChange={(e) => onStartDateChange(e.target.value)}
        data-testid="start-date-input"
      />
      <input
        type="date"
        value={endDate}
        onChange={(e) => onEndDateChange(e.target.value)}
        data-testid="end-date-input"
      />
    </div>
  ),
}));

const employeeUser: User = {
  id: 11,
  email: 'emp1@example.com',
  username: 'emp1',
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
};

const legacyProject: Project = {
  id: 101,
  name: 'Legacy Project',
  client_id: 99,
  billable_rate: '125',
  quickbooks_project_id: null,
  code: null,
  description: null,
  start_date: null,
  end_date: null,
  estimated_hours: null,
  budget_amount: null,
  currency: null,
  is_active: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const legacyTask: Task = {
  id: 201,
  project_id: 101,
  name: 'Legacy Task',
  code: 'LEG-T1',
  description: 'Legacy task',
  is_active: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const notificationsSummary: NotificationSummary = {
  total_count: 0,
  route_counts: {
    my_time: 0,
    time_off: 0,
    approvals: 0,
    admin: 0,
    dashboard: 0,
  },
  items: [],
};

describe('MyTimePage', () => {
  beforeEach(() => {
    const weekStart = startOfWeek(new Date(), { weekStartsOn: 0 });
    const monday = addDays(weekStart, 1);
    const mondayKey = format(monday, 'yyyy-MM-dd');

    const weeklyEntries: TimeEntry[] = [
      {
        id: 5001,
        user_id: 11,
        project_id: 101,
        task_id: 201,
        entry_date: mondayKey,
        hours: '6',
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
        project: legacyProject,
        task: legacyTask,
      },
    ];

    mocks.useAuth.mockReturnValue({ user: employeeUser });

    mocks.useTimeEntries.mockImplementation((params?: Record<string, unknown>) => {
      const isWeeklyGridCall = params?.sort_order === 'asc' && typeof params?.start_date === 'string';
      if (isWeeklyGridCall) {
        return { data: weeklyEntries, isLoading: false, error: null };
      }
      return { data: [], isLoading: false, error: null };
    });

    mocks.useCreateTimeEntry.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
    });
    mocks.useSubmitTimeEntries.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue([]),
      isPending: false,
    });
    mocks.useProjects.mockReturnValue({ data: [], isLoading: false });
    mocks.useTasks.mockReturnValue({ data: [], isLoading: false });
    mocks.useUpdateTimeEntry.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
    });
    mocks.useNotifications.mockReturnValue({ data: notificationsSummary });
    mocks.useWeeklySubmitStatus.mockReturnValue({
      data: {
        can_submit: false,
        reason: 'Weekly entry submission opens on 2026-03-20',
        due_date: '2026-03-20',
      },
    });
    mocks.useCreateTask.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({ id: 900 }),
      isPending: false,
    });
    mocks.useMarkNotificationRead.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
  });

  it('hydrates weekly grid hours without exposing inaccessible project/task options', async () => {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MyTimePage />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByDisplayValue('6')).toBeInTheDocument();
    expect(screen.queryByText('Legacy Project')).not.toBeInTheDocument();
    expect(screen.queryByText('Legacy Task')).not.toBeInTheDocument();
  });
});
