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
  email_verified: true,
  has_changed_password: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

describe('OrganizationalChart', () => {
  it('renders a single user as the root node', () => {
    const alice = baseUser({
      id: 1,
      full_name: 'Alice Admin',
      email: 'alice@example.com',
      username: 'alice',
      role: 'ADMIN',
      manager_id: null,
    });

    render(
      <OrganizationalChart
        users={[alice]}
        usersByManager={{}}
        topLevelUsers={[alice]}
      />,
    );

    expect(screen.getByText('Alice Admin')).toBeInTheDocument();
    // No empty-state message should render when there is at least one user.
    expect(screen.queryByTestId('org-chart-empty')).not.toBeInTheDocument();
  });

  it('renders an empty-state message when there are zero users', () => {
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

  it('renders a manager and their direct report unchanged (regression)', () => {
    const manager = baseUser({
      id: 1,
      full_name: 'Morgan Manager',
      email: 'morgan@example.com',
      username: 'morgan',
      role: 'MANAGER',
      manager_id: null,
    });
    const report = baseUser({
      id: 2,
      full_name: 'Riley Report',
      email: 'riley@example.com',
      username: 'riley',
      role: 'EMPLOYEE',
      manager_id: 1,
    });

    render(
      <OrganizationalChart
        users={[manager, report]}
        usersByManager={{ 1: [report] }}
        topLevelUsers={[manager]}
      />,
    );

    expect(screen.getByText('Morgan Manager')).toBeInTheDocument();
    expect(screen.getByText('Riley Report')).toBeInTheDocument();
    expect(screen.queryByTestId('org-chart-empty')).not.toBeInTheDocument();
  });
});
