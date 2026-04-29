import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { ManagerConversation } from './ManagerConversation';
import type { ManagerTeamMemberStatus, ManagerTeamOverviewResponse } from '@/types';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

const member = (overrides: Partial<ManagerTeamMemberStatus> = {}): ManagerTeamMemberStatus => ({
  user_id: 1,
  full_name: 'Person',
  working_days_in_week: 5,
  submitted_days: 5,
  is_on_pto_today: false,
  is_on_pto_this_week: false,
  upcoming_pto_starts_at: null,
  is_repeatedly_late: false,
  ...overrides,
});

const overview = (overrides: Partial<ManagerTeamOverviewResponse> = {}): ManagerTeamOverviewResponse => ({
  week_start: '2026-04-21',
  week_end: '2026-04-27',
  today: '2026-04-22',
  team_size: 0,
  members: [],
  pending_approvals_count: 0,
  pending_time_off_count: 0,
  rejected_recent_count: 0,
  pending_approvals_oldest_hours: null,
  pending_approvals_avg_hours: null,
  capacity_this_week: [],
  capacity_next_week: [],
  ...overrides,
});

const renderIt = (props: Partial<React.ComponentProps<typeof ManagerConversation>> = {}) =>
  render(
    <MemoryRouter>
      <ManagerConversation overview={undefined} {...props} />
    </MemoryRouter>,
  );

describe('ManagerConversation', () => {
  it('shows loading copy when overview is undefined', () => {
    renderIt();
    expect(screen.getByText(/loading your priorities/i)).toBeInTheDocument();
  });

  it('shows "no direct reports" path when team is empty', () => {
    renderIt({ overview: overview({ team_size: 0 }) });
    expect(screen.getByText(/no direct reports/i)).toBeInTheDocument();
  });

  it('renders the all-on-track callout when everyone is on track', () => {
    const m = member({ user_id: 1, full_name: 'Alice', submitted_days: 5, working_days_in_week: 5 });
    renderIt({ overview: overview({ team_size: 1, members: [m] }) });
    expect(screen.getByText(/everyone on your team is on track/i)).toBeInTheDocument();
  });

  it('names a member with a follow-up pattern by first name', () => {
    const frank = member({ user_id: 2, full_name: 'Frank Foster', is_repeatedly_late: true });
    renderIt({ overview: overview({ team_size: 1, members: [frank] }) });
    // Wording should soften "critical" → "needs follow-up" and lead
    // with the person's name.
    expect(screen.getByText(/frank/i)).toBeInTheDocument();
    expect(screen.getByText(/needs follow-up/i)).toBeInTheDocument();
    expect(screen.queryByText(/critical/i)).not.toBeInTheDocument();
  });

  it('renders the follow-up name as a clickable link that routes to that user\'s approvals', () => {
    mockNavigate.mockClear();
    const grace = member({ user_id: 42, full_name: 'Grace Kim', is_repeatedly_late: true });
    renderIt({ overview: overview({ team_size: 1, members: [grace] }) });
    fireEvent.click(screen.getByRole('button', { name: /^grace$/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/approvals?user_id=42');
  });

  it('routes "Review approvals" button to /approvals', () => {
    mockNavigate.mockClear();
    renderIt({ overview: overview({ team_size: 1, members: [member()], pending_approvals_count: 4 }) });
    fireEvent.click(screen.getByRole('button', { name: /review approvals \(4\)/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/approvals');
  });

  it('surfaces ingestion line and "Open inbox" action when ingestion is enabled with pending items', () => {
    mockNavigate.mockClear();
    renderIt({
      overview: overview({ team_size: 0 }),
      ingestionEnabled: true,
      pendingIngestionCount: 5,
    });
    expect(screen.getByText(/5 timesheets in the email inbox/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /open inbox \(5\)/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/ingestion/inbox');
  });

  it('does not surface ingestion when disabled', () => {
    renderIt({
      overview: overview({ team_size: 0 }),
      ingestionEnabled: false,
      pendingIngestionCount: 5,
    });
    expect(screen.queryByText(/email inbox/i)).not.toBeInTheDocument();
  });
});
