import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { WeeklyRoster } from './WeeklyRoster';
import type { ManagerTeamMemberStatus } from '@/types';

const mk = (overrides: Partial<ManagerTeamMemberStatus> = {}): ManagerTeamMemberStatus => ({
  user_id: 1,
  full_name: 'Default User',
  working_days_in_week: 5,
  submitted_days: 5,
  is_on_pto_today: false,
  is_on_pto_this_week: false,
  upcoming_pto_starts_at: null,
  is_repeatedly_late: false,
  ...overrides,
});

describe('WeeklyRoster', () => {
  it('shows empty state when there are no members', () => {
    render(<WeeklyRoster members={[]} />);
    expect(screen.getByText(/no team members/i)).toBeInTheDocument();
  });

  it('classifies a fully-submitted member as on-track', () => {
    render(<WeeklyRoster members={[mk({ user_id: 1, full_name: 'Alice', submitted_days: 5, working_days_in_week: 5 })]} />);
    expect(screen.getByText('1 on track')).toBeInTheDocument();
    expect(screen.getByText('0 behind')).toBeInTheDocument();
  });

  it('classifies a partially-submitted member as behind', () => {
    render(<WeeklyRoster members={[mk({ user_id: 2, full_name: 'Bob', submitted_days: 2, working_days_in_week: 5 })]} />);
    expect(screen.getByText('1 behind')).toBeInTheDocument();
  });

  it('classifies a member on PTO today as pto', () => {
    render(<WeeklyRoster members={[mk({ user_id: 3, full_name: 'Carol', is_on_pto_today: true, submitted_days: 0, working_days_in_week: 5 })]} />);
    expect(screen.getByText('1 on PTO')).toBeInTheDocument();
    // Not classified as "behind" even though submitted_days < working_days.
    expect(screen.getByText('0 behind')).toBeInTheDocument();
  });

  it('flags a repeatedly-late member as critical and shows the Late badge', () => {
    render(<WeeklyRoster members={[mk({ user_id: 4, full_name: 'Dan', is_repeatedly_late: true, submitted_days: 5, working_days_in_week: 5 })]} />);
    expect(screen.getByText('1 critical')).toBeInTheDocument();
    expect(screen.getByText('Late')).toBeInTheDocument();
  });

  it('orders critical → behind → pto → on-track', () => {
    render(
      <WeeklyRoster
        members={[
          mk({ user_id: 1, full_name: 'Sue Submit', submitted_days: 5, working_days_in_week: 5 }),
          mk({ user_id: 2, full_name: 'Pat PTO', is_on_pto_today: true }),
          mk({ user_id: 3, full_name: 'Bea Behind', submitted_days: 2, working_days_in_week: 5 }),
          mk({ user_id: 4, full_name: 'Cathy Critical', is_repeatedly_late: true }),
        ]}
      />,
    );
    const chips = screen.getAllByRole('button');
    expect(chips[0]).toHaveTextContent('Cathy Critical');
    expect(chips[1]).toHaveTextContent('Bea Behind');
    expect(chips[2]).toHaveTextContent('Pat PTO');
    expect(chips[3]).toHaveTextContent('Sue Submit');
  });

  it('fires onSelectEmployee with the user id', () => {
    const onSelectEmployee = vi.fn();
    render(<WeeklyRoster members={[mk({ user_id: 7, full_name: 'Test User' })]} onSelectEmployee={onSelectEmployee} />);
    fireEvent.click(screen.getByRole('button', { name: /Test User/i }));
    expect(onSelectEmployee).toHaveBeenCalledWith(7);
  });
});
