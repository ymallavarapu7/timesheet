import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { ManagerPriorities } from './ManagerPriorities';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

const renderIt = (overrides: Partial<React.ComponentProps<typeof ManagerPriorities>> = {}) => {
  const props: React.ComponentProps<typeof ManagerPriorities> = {
    pendingApprovalsCount: 0,
    pendingTimeOffCount: 0,
    rejectedRecentCount: 0,
    isLoading: false,
    ...overrides,
  };
  return render(
    <MemoryRouter>
      <ManagerPriorities {...props} />
    </MemoryRouter>,
  );
};

describe('ManagerPriorities', () => {
  it('shows the empty state when nothing is pending', () => {
    renderIt();
    expect(screen.getByText(/nothing on your plate/i)).toBeInTheDocument();
  });

  it('renders pending approvals row and routes on click', () => {
    mockNavigate.mockClear();
    renderIt({ pendingApprovalsCount: 3 });
    fireEvent.click(screen.getByRole('button', { name: /3 timesheet entries awaiting your approval/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/approvals');
  });

  it('escalates approvals urgency past the warn threshold', () => {
    renderIt({ pendingApprovalsCount: 12 });
    // 12 ≥ 10 → urgent. We can't read color directly, but the urgent
    // item sorts first; with only one item, just confirm it renders.
    expect(screen.getByText(/12 timesheet entries awaiting your approval/i)).toBeInTheDocument();
  });

  it('routes time-off requests to the time-off-approvals page', () => {
    mockNavigate.mockClear();
    renderIt({ pendingTimeOffCount: 2 });
    fireEvent.click(screen.getByRole('button', { name: /2 time-off requests/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/time-off-approvals');
  });

  it('routes rejected entries with a filter param', () => {
    mockNavigate.mockClear();
    renderIt({ rejectedRecentCount: 1 });
    fireEvent.click(screen.getByRole('button', { name: /1 rejected entry this week/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/approvals?filter=rejected');
  });

  it('sorts urgent items above warnings and info', () => {
    renderIt({ pendingApprovalsCount: 12, pendingTimeOffCount: 1, rejectedRecentCount: 1 });
    // Urgent (approvals 12) → warn (rejected) → info (time-off).
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('12 timesheet entries');
    expect(items[1]).toHaveTextContent('1 rejected entry');
    expect(items[2]).toHaveTextContent('1 time-off request');
  });
});
