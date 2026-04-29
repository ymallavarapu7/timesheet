import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ProjectHealthTable } from './ProjectHealthTable';
import type { ManagerProjectHealthRow } from '@/types';

const row = (overrides: Partial<ManagerProjectHealthRow> = {}): ManagerProjectHealthRow => ({
  project_id: 1,
  project_name: 'DXC',
  client_name: 'DXC',
  days_until_end: 30,
  hours_this_week: 12,
  budget_pct: 50,
  budget_hours_remaining: 20,
  health: 'good',
  ...overrides,
});

describe('ProjectHealthTable', () => {
  it('shows the empty state when no rows', () => {
    render(<ProjectHealthTable rows={[]} />);
    expect(screen.getByText(/no projects with team activity/i)).toBeInTheDocument();
  });

  it('renders a row with health chip and labeled time-left', () => {
    render(<ProjectHealthTable rows={[row({ project_name: 'Acme', client_name: 'Acme Co', health: 'at-risk', days_until_end: 4 })]} />);
    expect(screen.getByText('Acme')).toBeInTheDocument();
    expect(screen.getByText('Acme Co')).toBeInTheDocument();
    expect(screen.getByText('At risk')).toBeInTheDocument();
  });

  it('renders "Over" for negative days_until_end', () => {
    render(<ProjectHealthTable rows={[row({ days_until_end: -45, health: 'needs-attention' })]} />);
    expect(screen.getByText(/1 mo over/i)).toBeInTheDocument();
    expect(screen.getByText('Needs attention')).toBeInTheDocument();
  });

  it('shows "Open" for null days_until_end and "No budget" when budget_pct is null', () => {
    render(<ProjectHealthTable rows={[row({ days_until_end: null, budget_pct: null, budget_hours_remaining: null, health: 'not-set' })]} />);
    expect(screen.getByText('Open')).toBeInTheDocument();
    expect(screen.getByText('No budget')).toBeInTheDocument();
    expect(screen.getByText('Not set')).toBeInTheDocument();
  });

  it('marks over-budget rows with the percentage in red', () => {
    render(<ProjectHealthTable rows={[row({ budget_pct: 120, budget_hours_remaining: -3, health: 'needs-attention' })]} />);
    expect(screen.getByText('120%')).toBeInTheDocument();
    expect(screen.getByText(/3h over/i)).toBeInTheDocument();
  });
});
