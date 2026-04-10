import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ProfilePage } from './ProfilePage';
import type { UserProfile } from '@/types';

const mocks = vi.hoisted(() => ({
  useMyProfile: vi.fn(),
  useChangePassword: vi.fn(),
  useUpdateMyProfile: vi.fn(),
}));

vi.mock('@/hooks', () => ({
  useMyProfile: mocks.useMyProfile,
  useChangePassword: mocks.useChangePassword,
  useUpdateMyProfile: mocks.useUpdateMyProfile,
}));

vi.mock('@/components', () => ({
  Header: () => <div>Header</div>,
  Loading: () => <div>Loading</div>,
  Error: ({ message }: { message: string }) => <div>{message}</div>,
}));

describe('ProfilePage', () => {
  beforeEach(() => {
    const profile: UserProfile = {
      id: 11,
      email: 'employee@example.com',
      username: 'employee',
      full_name: 'Employee One',
      title: 'Engineer',
      department: 'Engineering',
      role: 'EMPLOYEE',
      has_changed_password: true,
      manager_id: 2,
      manager_name: 'Manager User',
      direct_reports: [],
      supervisor_chain: [],
    };

    mocks.useMyProfile.mockReturnValue({ data: profile, isLoading: false, error: null });
    mocks.useChangePassword.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    mocks.useUpdateMyProfile.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  });

  it('renders profile details and password update sections', () => {
    render(<ProfilePage />);

    expect(screen.getByText('My Profile')).toBeInTheDocument();
    expect(screen.getByText('Profile Details')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Update Password' })).toBeInTheDocument();
    expect(screen.getByDisplayValue('Employee One')).toBeInTheDocument();
  });
});
