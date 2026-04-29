import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { ManagerGlanceTiles } from './ManagerGlanceTiles';
import type { ManagerTeamOverviewResponse } from '@/types';

const overview: ManagerTeamOverviewResponse = {
  week_start: '2026-04-21',
  week_end: '2026-04-27',
  today: '2026-04-22',
  team_size: 20,
  members: Array.from({ length: 14 }, (_, i) => ({
    user_id: i + 1,
    full_name: `Person ${i + 1}`,
    working_days_in_week: 5,
    submitted_days: 5,
    is_on_pto_today: false,
    is_on_pto_this_week: false,
    upcoming_pto_starts_at: null,
    is_repeatedly_late: false,
  })),
  pending_approvals_count: 7,
  pending_time_off_count: 1,
  rejected_recent_count: 0,
  pending_approvals_oldest_hours: 14,
  pending_approvals_avg_hours: 8,
  capacity_this_week: [
    { user_id: 100, full_name: 'Eva', leave_type: 'vacation', days_in_window: 2 },
    { user_id: 101, full_name: 'Sarah', leave_type: 'vacation', days_in_window: 2 },
  ],
  capacity_next_week: [
    { user_id: 102, full_name: 'Tom', leave_type: 'vacation', days_in_window: 5 },
  ],
};

const renderIt = (props: Partial<React.ComponentProps<typeof ManagerGlanceTiles>> = {}) =>
  render(
    <MemoryRouter>
      <ManagerGlanceTiles overview={overview} {...props} />
    </MemoryRouter>,
  );

describe('ManagerGlanceTiles', () => {
  it('shows team-on-track ratio', () => {
    renderIt();
    expect(screen.getByText('14/20')).toBeInTheDocument();
  });

  it('renders pending approvals + oldest age', () => {
    renderIt();
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText(/oldest 14h ago/i)).toBeInTheDocument();
  });

  it('renders avg approval age within SLA when below 24h', () => {
    renderIt();
    expect(screen.getByText('8h')).toBeInTheDocument();
    expect(screen.getByText(/within sla/i)).toBeInTheDocument();
  });

  it('shows the Inbox tile when ingestion is enabled', () => {
    renderIt({ ingestionEnabled: true, pendingIngestionCount: 5, ingestionOldestHours: 8 });
    expect(screen.getByText('Inbox')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('shows Project alerts tile when ingestion is disabled', () => {
    renderIt({ ingestionEnabled: false, projectAlertCount: 3 });
    expect(screen.getByText('Project alerts')).toBeInTheDocument();
    // 3 is unique in this scenario (PTO this week is 2, next week is 1).
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('renders 5 placeholder tiles while overview is loading', () => {
    render(
      <MemoryRouter>
        <ManagerGlanceTiles overview={undefined} />
      </MemoryRouter>,
    );
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBe(5);
  });
});
