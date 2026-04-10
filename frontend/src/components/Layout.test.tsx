import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { EmptyState, Error, Loading } from './Layout';

describe('Layout components', () => {
  it('renders loading message', () => {
    render(<Loading message="Fetching entries..." />);

    expect(screen.getByText('Fetching entries...')).toBeInTheDocument();
  });

  it('renders error with action button and triggers action', () => {
    const retry = vi.fn();
    render(
      <Error
        title="Something went wrong"
        message="Unable to load data"
        action={retry}
        actionLabel="Retry"
      />
    );

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByText('Unable to load data')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('renders empty state message', () => {
    render(<EmptyState message="No entries yet" />);

    expect(screen.getByText('No entries yet')).toBeInTheDocument();
  });
});
