import { fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AdminPage } from './AdminPage';
import type { Project, User } from '@/types';

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  useIsPlatformAdmin: vi.fn(),
  useUsers: vi.fn(),
  useProjects: vi.fn(),
  useNotifications: vi.fn(),
  useCreateUser: vi.fn(),
  useUpdateUser: vi.fn(),
  useDeleteUser: vi.fn(),
}));

vi.mock('@/hooks', () => ({
  useAuth: mocks.useAuth,
  useIsPlatformAdmin: mocks.useIsPlatformAdmin,
  useUsers: mocks.useUsers,
  useProjects: mocks.useProjects,
  useNotifications: mocks.useNotifications,
  useCreateUser: mocks.useCreateUser,
  useUpdateUser: mocks.useUpdateUser,
  useDeleteUser: mocks.useDeleteUser,
  useResetUserPassword: () => ({ mutate: vi.fn(), isPending: false }),
  useResendVerification: () => ({ mutate: vi.fn(), isPending: false }),
  useBulkDeleteUsers: () => ({ mutate: vi.fn(), isPending: false }),
  useUnlockUserTimesheet: () => ({ mutate: vi.fn(), isPending: false }),
  useUserEmailAliases: () => ({ data: [], isLoading: false }),
  useAddUserEmailAlias: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteUserEmailAlias: () => ({ mutate: vi.fn(), isPending: false }),
  useClients: () => ({ data: [], isLoading: false }),
  useDepartments: () => ({ data: [], isLoading: false }),
  useCreateDepartment: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteDepartment: () => ({ mutate: vi.fn(), isPending: false }),
  useLeaveTypes: () => ({ data: [], isLoading: false }),
  useCreateLeaveType: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateLeaveType: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteLeaveType: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock('@/components', () => ({
  Header: () => <div>Header</div>,
  Loading: () => <div>Loading</div>,
  Error: ({ message }: { message: string }) => <div>{message}</div>,
  OrganizationalChart: () => <div>OrgChart</div>,
  SearchInput: ({ value, onChange, placeholder, className }: { value: string; onChange: (v: string) => void; placeholder?: string; className?: string }) => (
    <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={className} />
  ),
}));

describe('AdminPage', () => {
  beforeEach(() => {
    const currentUser: User = {
      id: 1,
      email: 'admin@example.com',
      username: 'admin',
      full_name: 'Admin User',
      title: 'Administrator',
      department: 'Operations',
      role: 'ADMIN',
      is_active: true,
      has_changed_password: true, email_verified: true, tenant_id: 1,
      manager_id: null,
      project_ids: [],
      created_at: '2026-03-01T00:00:00Z',
      updated_at: '2026-03-01T00:00:00Z',
    };

    const users: User[] = [
      currentUser,
      {
        id: 2,
        email: 'manager@example.com',
        username: 'manager',
        full_name: 'Manager User',
        title: 'Engineering Manager',
        department: 'Engineering',
        role: 'MANAGER',
        is_active: true,
        has_changed_password: true, email_verified: true, tenant_id: 1,
        manager_id: 1,
        project_ids: [101],
        created_at: '2026-03-01T00:00:00Z',
        updated_at: '2026-03-01T00:00:00Z',
      },
      {
        id: 3,
        email: 'senior.manager@example.com',
        username: 'senior-manager',
        full_name: 'Senior Manager User',
        title: 'Senior Manager',
        department: 'Engineering',
        role: 'SENIOR_MANAGER',
        is_active: true,
        has_changed_password: true, email_verified: true, tenant_id: 1,
        manager_id: null,
        project_ids: [],
        created_at: '2026-03-01T00:00:00Z',
        updated_at: '2026-03-01T00:00:00Z',
      },
      {
        id: 4,
        email: 'manager.peer@example.com',
        username: 'manager-peer',
        full_name: 'Peer Manager',
        title: 'Operations Manager',
        department: 'Operations',
        role: 'MANAGER',
        is_active: true,
        has_changed_password: true, email_verified: true, tenant_id: 1,
        manager_id: 3,
        project_ids: [],
        created_at: '2026-03-01T00:00:00Z',
        updated_at: '2026-03-01T00:00:00Z',
      },
    ];

    const projects: Project[] = [
      {
        id: 101,
        name: 'Alpha Project',
        client_id: 5,
        billable_rate: '100',
        quickbooks_project_id: null,
        code: null,
        description: null,
        start_date: null,
        end_date: null,
        estimated_hours: null,
        budget_amount: null,
        currency: null,
        is_active: true,
        created_at: '2026-03-01T00:00:00Z',
        updated_at: '2026-03-01T00:00:00Z',
      },
    ];

    mocks.useAuth.mockReturnValue({ user: currentUser, refreshUser: vi.fn().mockResolvedValue(undefined) });
    mocks.useIsPlatformAdmin.mockReturnValue(false);
    mocks.useUsers.mockReturnValue({ data: users, isLoading: false, error: null, refetch: vi.fn().mockResolvedValue(undefined) });
    mocks.useProjects.mockReturnValue({ data: projects, isLoading: false, error: null });
    mocks.useNotifications.mockReturnValue({ data: { items: [] } });
    mocks.useCreateUser.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    mocks.useUpdateUser.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    mocks.useDeleteUser.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  });

  it('renders user management portal shell', () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AdminPage />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(screen.getByText('User Management')).toBeInTheDocument();
    expect(screen.getByText('OrgChart')).toBeInTheDocument();
  });

  it('shows only senior manager or CEO options for manager reports-to selection', () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AdminPage />
        </MemoryRouter>
      </QueryClientProvider>
    );

    const managerEmailCell = screen.getByText('manager@example.com');
    const managerRow = managerEmailCell.closest('tr');
    expect(managerRow).toBeTruthy();
    fireEvent.click(within(managerRow as HTMLElement).getByRole('button', { name: /user actions/i }));
    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }));

    const reportsToLabel = screen.getByText('Reports To');
    const reportsToSelect = reportsToLabel.parentElement?.querySelector('select') as HTMLSelectElement;
    expect(reportsToSelect).toBeTruthy();
    const optionLabels = Array.from(reportsToSelect.options).map((option) => option.textContent ?? '');

    expect(optionLabels).toContain('Unassigned');
    expect(optionLabels).toContain('Senior Manager User');
    expect(optionLabels).not.toContain('Peer Manager');
  });

  it('limits admin reports-to options to manager levels and preselects assigned manager', () => {
    const currentUser: User = {
      id: 99,
      email: 'operator@example.com',
      username: 'operator',
      full_name: 'Ops Admin',
      title: 'Administrator',
      department: 'Operations',
      role: 'ADMIN',
      is_active: true,
      has_changed_password: true, email_verified: true, tenant_id: 1,
      manager_id: null,
      project_ids: [],
      created_at: '2026-03-01T00:00:00Z',
      updated_at: '2026-03-01T00:00:00Z',
    };

    const users: User[] = [
      currentUser,
      {
        id: 1,
        email: 'ops.manager@example.com',
        username: 'ops-manager',
        full_name: 'Olivia Ops Manager',
        title: 'Operations Manager',
        department: 'Operations',
        role: 'MANAGER',
        is_active: true,
        has_changed_password: true, email_verified: true, tenant_id: 1,
        manager_id: null,
        project_ids: [],
        created_at: '2026-03-01T00:00:00Z',
        updated_at: '2026-03-01T00:00:00Z',
      },
      {
        id: 3,
        email: 'ceo@example.com',
        username: 'ceo',
        full_name: 'Casey CEO',
        title: 'Chief Executive Officer',
        department: 'Executive',
        role: 'CEO',
        is_active: true,
        has_changed_password: true, email_verified: true, tenant_id: 1,
        manager_id: null,
        project_ids: [],
        created_at: '2026-03-01T00:00:00Z',
        updated_at: '2026-03-01T00:00:00Z',
      },
      {
        id: 2,
        email: 'admin@example.com',
        username: 'admin',
        full_name: 'Bharat Mallavarapu',
        title: 'System Administrator',
        department: 'Administration',
        role: 'ADMIN',
        is_active: true,
        has_changed_password: true, email_verified: true, tenant_id: 1,
        manager_id: 1,
        project_ids: [],
        created_at: '2026-03-01T00:00:00Z',
        updated_at: '2026-03-01T00:00:00Z',
      },
    ];

    mocks.useAuth.mockReturnValue({ user: currentUser, refreshUser: vi.fn().mockResolvedValue(undefined) });
    mocks.useUsers.mockReturnValue({ data: users, isLoading: false, error: null, refetch: vi.fn().mockResolvedValue(undefined) });

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AdminPage />
        </MemoryRouter>
      </QueryClientProvider>
    );

    const adminEmailCell = screen.getByText('admin@example.com');
    const adminRow = adminEmailCell.closest('tr');
    expect(adminRow).toBeTruthy();
    fireEvent.click(within(adminRow as HTMLElement).getByRole('button', { name: /user actions/i }));
    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }));

    const reportsToLabel = screen.getByText('Reports To');
    const reportsToSelect = reportsToLabel.parentElement?.querySelector('select') as HTMLSelectElement;
    expect(reportsToSelect).toBeTruthy();
    const optionLabels = Array.from(reportsToSelect.options).map((option) => option.textContent ?? '');

    expect(optionLabels).toContain('Unassigned');
    expect(optionLabels).toContain('Olivia Ops Manager');
    expect(optionLabels).not.toContain('Casey CEO');
    expect(reportsToSelect.value).toBe('1');
  });
});
