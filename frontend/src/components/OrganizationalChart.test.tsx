import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { OrganizationalChart } from './OrganizationalChart';
import type { User } from '@/types';

const baseUser = (overrides: Partial<User>): User => ({
  id: 0,
  tenant_id: 1,
  email: 'u@example.com',
  username: 'u',
  full_name: 'User',
  role: 'EMPLOYEE',
  is_active: true,
  is_external: false,
  email_verified: true,
  has_changed_password: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

describe('OrganizationalChart', () => {
  it('renders empty state when there are no users', () => {
    render(
      <OrganizationalChart
        users={[]}
        usersByManager={{}}
        topLevelUsers={[]}
      />,
    );
    expect(screen.getByTestId('org-chart-empty')).toBeInTheDocument();
    expect(screen.getByText(/no team members yet/i)).toBeInTheDocument();
  });

  it('renders a single internal user as root', () => {
    const alice = baseUser({ id: 1, full_name: 'Alice Admin', role: 'ADMIN', manager_id: null });
    render(
      <OrganizationalChart
        users={[alice]}
        usersByManager={{}}
        topLevelUsers={[alice]}
      />,
    );
    expect(screen.getByText('Alice Admin')).toBeInTheDocument();
    expect(screen.queryByTestId('org-chart-empty')).not.toBeInTheDocument();
  });

  it('renders a manager and their direct report', () => {
    const manager = baseUser({ id: 1, full_name: 'Morgan Manager', role: 'MANAGER', manager_id: null });
    const report  = baseUser({ id: 2, full_name: 'Riley Report',   role: 'EMPLOYEE', manager_id: 1 });
    render(
      <OrganizationalChart
        users={[manager, report]}
        usersByManager={{ 1: [report] }}
        topLevelUsers={[manager]}
      />,
    );
    expect(screen.getByText('Morgan Manager')).toBeInTheDocument();
    expect(screen.getByText('Riley Report')).toBeInTheDocument();
  });

  it('does not include external users in the internal tree', () => {
    const internal = baseUser({ id: 1, full_name: 'Internal User', role: 'EMPLOYEE', is_external: false, manager_id: null });
    const external = baseUser({ id: 2, full_name: 'External User', role: 'EMPLOYEE', is_external: true,  manager_id: null });
    render(
      <OrganizationalChart
        users={[internal, external]}
        usersByManager={{}}
        topLevelUsers={[internal, external]}
      />,
    );
    expect(screen.getByText('Internal User')).toBeInTheDocument();
    expect(screen.queryByText('External User')).not.toBeInTheDocument();
  });
});
