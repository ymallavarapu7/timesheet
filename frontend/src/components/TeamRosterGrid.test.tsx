import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { TeamRosterGrid } from './TeamRosterGrid';
import type { User } from '@/types';

const mkUser = (id: number, full_name: string): User => ({
  id,
  tenant_id: 1,
  email: `${full_name.toLowerCase().replace(/\s+/g, '.')}@example.com`,
  username: `u${id}`,
  full_name,
  role: 'EMPLOYEE',
  is_active: true,
  email_verified: true,
  has_changed_password: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
});

describe('TeamRosterGrid', () => {
  it('renders the empty-state when there are no team members', () => {
    render(<TeamRosterGrid submitted={[]} grace={[]} missing={[]} />);
    expect(screen.getByText(/no team members/i)).toBeInTheDocument();
  });

  it('renders all three buckets and shows aggregate counts', () => {
    render(
      <TeamRosterGrid
        submitted={[mkUser(1, 'Alice Andrews')]}
        grace={[mkUser(2, 'Bob Burns'), mkUser(3, 'Carol Chen')]}
        missing={[mkUser(4, 'Dan Diaz')]}
      />,
    );
    expect(screen.getByText('1 submitted')).toBeInTheDocument();
    expect(screen.getByText('2 in grace window')).toBeInTheDocument();
    expect(screen.getByText('1 not submitted')).toBeInTheDocument();
    // All four chips render.
    expect(screen.getByRole('button', { name: /Alice Andrews/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Dan Diaz/i })).toBeInTheDocument();
  });

  it('orders chips urgent-first (missing → grace → submitted), alpha within bucket', () => {
    render(
      <TeamRosterGrid
        submitted={[mkUser(1, 'Sue Submitter')]}
        grace={[mkUser(2, 'Greta Grace'), mkUser(3, 'Aaron Alpha')]}
        missing={[mkUser(4, 'Mia Missing'), mkUser(5, 'Bart Bygone')]}
      />,
    );
    const chips = screen.getAllByRole('button');
    const names = chips.map((b) => b.textContent ?? '');
    // Missing first (alpha): Bart Bygone, Mia Missing
    expect(names[0]).toContain('Bart Bygone');
    expect(names[1]).toContain('Mia Missing');
    // Grace next (alpha): Aaron Alpha, Greta Grace
    expect(names[2]).toContain('Aaron Alpha');
    expect(names[3]).toContain('Greta Grace');
    // Submitted last
    expect(names[4]).toContain('Sue Submitter');
  });

  it('fires onSelectEmployee with the user id when a chip is clicked', () => {
    const onSelectEmployee = vi.fn();
    render(
      <TeamRosterGrid
        submitted={[mkUser(7, 'Test User')]}
        grace={[]}
        missing={[]}
        onSelectEmployee={onSelectEmployee}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Test User/i }));
    expect(onSelectEmployee).toHaveBeenCalledWith(7);
  });

  it('marks the selected chip with aria-pressed=true', () => {
    render(
      <TeamRosterGrid
        submitted={[mkUser(1, 'One'), mkUser(2, 'Two')]}
        grace={[]}
        missing={[]}
        selectedUserId={2}
      />,
    );
    const one = screen.getByRole('button', { name: /^One/i });
    const two = screen.getByRole('button', { name: /^Two/i });
    expect(one).toHaveAttribute('aria-pressed', 'false');
    expect(two).toHaveAttribute('aria-pressed', 'true');
  });

  it('renders initials avatars from full names', () => {
    render(<TeamRosterGrid submitted={[mkUser(1, 'Alice Andrews')]} grace={[]} missing={[]} />);
    const chip = screen.getByRole('button', { name: /Alice Andrews/i });
    expect(within(chip).getByText('AA')).toBeInTheDocument();
  });
});
