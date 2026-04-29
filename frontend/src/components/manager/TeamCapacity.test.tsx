import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { TeamCapacity } from './TeamCapacity';
import type { ManagerTeamCapacityEntry } from '@/types';

const row = (overrides: Partial<ManagerTeamCapacityEntry> = {}): ManagerTeamCapacityEntry => ({
  user_id: 1,
  full_name: 'Alice',
  leave_type: 'vacation',
  days_in_window: 1,
  ...overrides,
});

describe('TeamCapacity', () => {
  it('renders empty messages when both windows are empty', () => {
    render(<TeamCapacity teamSize={5} thisWeek={[]} nextWeek={[]} />);
    expect(screen.getAllByText(/no pto scheduled/i)).toHaveLength(2);
    expect(screen.getAllByText(/5\/5 available/)).toHaveLength(2);
  });

  it('shows the available headcount per window deducting distinct people on PTO', () => {
    render(
      <TeamCapacity
        teamSize={5}
        thisWeek={[
          row({ user_id: 1, full_name: 'Alice', leave_type: 'vacation', days_in_window: 2 }),
          row({ user_id: 1, full_name: 'Alice', leave_type: 'sick', days_in_window: 1 }),
          row({ user_id: 2, full_name: 'Bob', leave_type: 'vacation', days_in_window: 5 }),
        ]}
        nextWeek={[]}
      />,
    );
    // Two distinct people on PTO this week; available = 5 - 2 = 3.
    expect(screen.getByText('3/5 available')).toBeInTheDocument();
  });

  it('renders one row per (user, leave_type) pair', () => {
    render(
      <TeamCapacity
        teamSize={4}
        thisWeek={[]}
        nextWeek={[
          row({ user_id: 1, full_name: 'Alice', leave_type: 'vacation', days_in_window: 3 }),
          row({ user_id: 1, full_name: 'Alice', leave_type: 'sick', days_in_window: 1 }),
        ]}
      />,
    );
    expect(screen.getByText('vacation')).toBeInTheDocument();
    expect(screen.getByText('sick')).toBeInTheDocument();
  });

  it('uses singular vs plural day labels', () => {
    render(
      <TeamCapacity
        teamSize={3}
        thisWeek={[
          row({ user_id: 1, full_name: 'Alice', leave_type: 'vacation', days_in_window: 1 }),
          row({ user_id: 2, full_name: 'Bob', leave_type: 'vacation', days_in_window: 3 }),
        ]}
        nextWeek={[]}
      />,
    );
    expect(screen.getByText('1 day')).toBeInTheDocument();
    expect(screen.getByText('3 days')).toBeInTheDocument();
  });
});
