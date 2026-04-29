import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SystemHealthCard } from './SystemHealthCard';

describe('SystemHealthCard', () => {
  it('renders label, subtitle, and the Healthy chip', () => {
    render(<SystemHealthCard label="Database" status="healthy" subtitle="Last query 2s ago" />);
    expect(screen.getByText('Database')).toBeInTheDocument();
    expect(screen.getByText('Last query 2s ago')).toBeInTheDocument();
    expect(screen.getByText('Healthy')).toBeInTheDocument();
  });

  it('shows the Attention chip when status is attention', () => {
    render(<SystemHealthCard label="Email Ingestion" status="attention" subtitle="Last fetch 4h ago" />);
    expect(screen.getByText('Attention')).toBeInTheDocument();
  });

  it('shows the Checking… chip when loading', () => {
    render(<SystemHealthCard label="OpenAI" status="loading" subtitle="Checking…" />);
    expect(screen.getAllByText('Checking…')).not.toHaveLength(0);
  });

  it('renders 24 sparkline bars when no data is provided', () => {
    const { container } = render(
      <SystemHealthCard label="X" status="healthy" subtitle="Reachable" />,
    );
    const bars = container.querySelectorAll('.flex.h-8 > span');
    expect(bars).toHaveLength(24);
  });

  it('truncates an over-long sparkline to the most recent 24 buckets', () => {
    const tooMany = Array.from({ length: 50 }, (_, i) => i / 50);
    const { container } = render(
      <SystemHealthCard label="X" status="healthy" subtitle="Reachable" sparkline={tooMany} />,
    );
    const bars = container.querySelectorAll('.flex.h-8 > span');
    expect(bars).toHaveLength(24);
  });

  it('left-pads a short sparkline with empty buckets up to 24', () => {
    const { container } = render(
      <SystemHealthCard label="X" status="healthy" subtitle="Reachable" sparkline={[0.6, 0.7, 0.8]} />,
    );
    const bars = container.querySelectorAll('.flex.h-8 > span');
    expect(bars).toHaveLength(24);
  });
});
