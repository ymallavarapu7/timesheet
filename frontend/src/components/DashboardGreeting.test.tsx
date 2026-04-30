import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DashboardGreeting } from './DashboardGreeting';

describe('DashboardGreeting', () => {
  it('uses the first name from a full name', () => {
    render(<DashboardGreeting userFullName="Bharat Mallavarapu" />);
    // Time-of-day prefix is environment-dependent; check the comma +
    // first name part regardless of which prefix fires.
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/, Bharat\./);
  });

  it('handles a single-word name', () => {
    render(<DashboardGreeting userFullName="Madonna" />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/, Madonna\./);
  });

  it('falls back to the time-only greeting when name is missing', () => {
    render(<DashboardGreeting userFullName={null} />);
    expect(screen.getByRole('heading', { level: 1 })).not.toHaveTextContent(/,/);
  });

  it('renders a date label above the greeting', () => {
    render(<DashboardGreeting userFullName="Bharat" dateLabel="Thursday, Apr 30" />);
    expect(screen.getByText('Thursday, Apr 30')).toBeInTheDocument();
  });
});
