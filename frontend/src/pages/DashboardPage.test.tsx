import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { DashboardPage } from './DashboardPage';
import type { DashboardDayBreakdown, NotificationSummary, User } from '@/types';

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  useChangePassword: vi.fn(),
  useClients: vi.fn(),
  useDashboardAnalytics: vi.fn(),
  useDashboardRecentActivity: vi.fn(),
  useNotifications: vi.fn(),
  useProjects: vi.fn(),
  useTeamDailyOverview: vi.fn(),
  useTeamEmployees: vi.fn(),
  useTenants: vi.fn(),
  useUsers: vi.fn(),
}));

vi.mock('@/hooks', () => ({
  useAuth: mocks.useAuth,
  useChangePassword: mocks.useChangePassword,
  useClients: mocks.useClients,
  useDashboardAnalytics: mocks.useDashboardAnalytics,
  useDashboardRecentActivity: mocks.useDashboardRecentActivity,
  useNotifications: mocks.useNotifications,
  useProjects: mocks.useProjects,
  useTeamDailyOverview: mocks.useTeamDailyOverview,
  useTeamEmployees: mocks.useTeamEmployees,
  useTenants: mocks.useTenants,
  useUsers: mocks.useUsers,
  useWeekStartsOn: () => 1,
  useAdminSystemHealth: () => ({ data: undefined, isLoading: false }),
  useCanReview: () => false,
  useIngestionEnabled: () => false,
  useIngestionTimesheets: () => ({ data: { items: [] }, isLoading: false }),
  useManagerProjectHealth: () => ({ data: undefined, isLoading: false }),
  useManagerTeamOverview: () => ({ data: undefined, isLoading: false }),
  useTimeEntries: () => ({ data: [], isLoading: false }),
}));

vi.mock('@/components', () => ({
  Header: () => <div>Header</div>,
  Loading: () => <div>Loading</div>,
  ChangePasswordModal: () => null,
  AdminActionQueue: () => null,
  DashboardGreeting: () => null,
  SystemHealthCard: () => null,
  WeeklyRoster: () => null,
  ManagerConversation: () => null,
  ManagerGlanceTiles: () => null,
  ProjectHealthTable: () => null,
  QuickLogButton: () => null,
}));

const employeeUser: User = {
  id: 10,
  email: 'employee@example.com',
  username: 'employee',
  full_name: 'Employee User',
  title: 'Engineer',
  department: 'Engineering',
  role: 'EMPLOYEE',
  is_active: true,
  has_changed_password: true, email_verified: true, tenant_id: 1,
  manager_id: null,
  project_ids: [1],
  created_at: '2026-03-01T00:00:00Z',
  updated_at: '2026-03-01T00:00:00Z',
};

const dailyBreakdown: DashboardDayBreakdown[] = [
  {
    entry_date: '2026-03-16',
    formatted_date: 'Mon, Mar 16',
    hours: '10',
    segments: [
      {
        project_id: 1,
        project_name: 'AI Platform Development',
        client_name: 'Tech Innovations Inc',
        hours: '10',
        entries: [
          {
            entry_id: 100,
            project_id: 1,
            project_name: 'AI Platform Development',
            client_name: 'Tech Innovations Inc',
            status: 'APPROVED',
            description: 'Worked on project tasks',
            hours: '10',
            entry_date: '2026-03-16',
          },
        ],
      },
    ],
  },
];

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

describe('DashboardPage', () => {
  beforeEach(() => {
    mocks.useAuth.mockReturnValue({
      user: employeeUser,
      refreshUser: vi.fn().mockResolvedValue(undefined),
    });
    mocks.useChangePassword.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
    });
    mocks.useClients.mockReturnValue({ data: [], isLoading: false, error: null });
    mocks.useDashboardRecentActivity.mockReturnValue({ data: [], isLoading: false });
    mocks.useProjects.mockReturnValue({ data: [], isLoading: false });
    mocks.useTeamEmployees.mockReturnValue({ data: [], isLoading: false });
    mocks.useTeamDailyOverview.mockReturnValue({ data: undefined, isLoading: false });
    mocks.useTenants.mockReturnValue({ data: [], isLoading: false, error: null });
    mocks.useUsers.mockReturnValue({ data: [], isLoading: false, error: null });
    mocks.useNotifications.mockReturnValue({
      data: notificationsSummary,
      isLoading: false,
      error: null,
    });
    mocks.useDashboardAnalytics.mockReturnValue({
      data: {
        total_hours: '10',
        billable_hours: '10',
        non_billable_hours: '0',
        top_project_name: 'AI Platform Development',
        top_client_name: 'Tech Innovations Inc',
        daily_breakdown: dailyBreakdown,
        project_breakdown: [
          {
            project_id: 1,
            project_name: 'AI Platform Development',
            client_name: 'Tech Innovations Inc',
            hours: '10',
            percentage: 100,
          },
        ],
        top_activities: [
          {
            description: 'Worked on project tasks',
            project_name: 'AI Platform Development',
            hours: '10',
          },
        ],
      },
      isLoading: false,
    });
  });

  it('renders integrated weekly context and summary metrics', () => {
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    );

    expect(screen.getByText('Weekly View')).toBeInTheDocument();
    expect(screen.getByText('Total time')).toBeInTheDocument();
    expect(screen.getByText('Top Project')).toBeInTheDocument();
    expect(screen.getByText('Top Client')).toBeInTheDocument();
    expect(screen.getAllByText('AI Platform Development').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Tech Innovations Inc').length).toBeGreaterThan(0);
  });
});
