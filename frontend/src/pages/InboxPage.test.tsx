import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { InboxPage } from './InboxPage';
import type { IngestionTimesheetSummary } from '@/types';

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  useBulkReprocessEmails: vi.fn(),
  useBulkDeleteIngestedEmails: vi.fn(),
  useClients: vi.fn(),
  useDeleteIngestedEmail: vi.fn(),
  useFetchJobStatus: vi.fn(),
  useIngestionTimesheets: vi.fn(),
  useMailboxes: vi.fn(),
  useReprocessIngestionEmail: vi.fn(),
  useReprocessSkippedEmails: vi.fn(),
  useSkippedEmails: vi.fn(),
  useTriggerFetchEmails: vi.fn(),
  reprocessMutate: vi.fn(),
}));

vi.mock('@/hooks', () => ({
  useAuth: mocks.useAuth,
  useBulkReprocessEmails: mocks.useBulkReprocessEmails,
  useBulkDeleteIngestedEmails: mocks.useBulkDeleteIngestedEmails,
  useClients: mocks.useClients,
  useDeleteIngestedEmail: mocks.useDeleteIngestedEmail,
  useFetchJobStatus: mocks.useFetchJobStatus,
  useIngestionTimesheets: mocks.useIngestionTimesheets,
  useMailboxes: mocks.useMailboxes,
  useReprocessIngestionEmail: mocks.useReprocessIngestionEmail,
  useReprocessSkippedEmails: mocks.useReprocessSkippedEmails,
  useSkippedEmails: mocks.useSkippedEmails,
  useTriggerFetchEmails: mocks.useTriggerFetchEmails,
}));

vi.mock('@/components', () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  Loading: ({ message }: { message: string }) => <div>{message}</div>,
}));

vi.mock('@/components/ui/BulkSelectBar', () => ({
  BulkSelectBar: () => <div data-testid="bulk-select-bar" />,
}));

const TENANT_ID = 42;

const makeSkippedSummary = (overrides: Partial<IngestionTimesheetSummary> = {}): IngestionTimesheetSummary => ({
  id: overrides.id ?? Math.floor(Math.random() * 1_000_000),
  tenant_id: TENANT_ID,
  email_id: overrides.email_id ?? Math.floor(Math.random() * 1_000_000),
  attachment_id: null,
  subject: 'Timesheet (skipped)',
  sender_email: 'someone@example.com',
  sender_name: null,
  employee_id: null,
  employee_name: null,
  extracted_employee_name: null,
  extracted_supervisor_name: null,
  client_id: null,
  client_name: null,
  period_start: null,
  period_end: null,
  total_hours: null,
  status: 'skipped',
  push_status: null,
  time_entries_created: false,
  llm_anomalies: null,
  received_at: null,
  submitted_at: null,
  reviewed_at: null,
  created_at: '2026-04-22T00:00:00Z',
  ...overrides,
});

const setupHooks = (opts: {
  skippedCount: number;
  isBusy?: boolean;
} = { skippedCount: 0 }) => {
  const skippedTimesheets = Array.from({ length: opts.skippedCount }, (_, i) =>
    makeSkippedSummary({ id: i + 1, email_id: 1000 + i }),
  );

  mocks.useAuth.mockReturnValue({ user: { tenant_id: TENANT_ID, role: 'ADMIN' } });
  mocks.useIngestionTimesheets.mockReturnValue({
    data: skippedTimesheets,
    isLoading: false,
  });
  mocks.useSkippedEmails.mockReturnValue({
    data: { emails: [], total: 0 },
    isLoading: false,
  });
  mocks.useMailboxes.mockReturnValue({ data: [] });
  mocks.useClients.mockReturnValue({ data: [] });
  mocks.useFetchJobStatus.mockReturnValue({ data: null });

  const noopMutation = (isPending = false) => ({
    mutateAsync: vi.fn().mockResolvedValue({ job_id: 'job-1', message: 'ok' }),
    mutate: vi.fn(),
    isPending,
  });
  mocks.useTriggerFetchEmails.mockReturnValue(noopMutation());
  mocks.useReprocessSkippedEmails.mockReturnValue({
    mutateAsync: mocks.reprocessMutate.mockResolvedValue({ job_id: 'job-reprocess-all' }),
    mutate: vi.fn(),
    isPending: Boolean(opts.isBusy),
  });
  mocks.useReprocessIngestionEmail.mockReturnValue(noopMutation());
  mocks.useDeleteIngestedEmail.mockReturnValue(noopMutation());
  mocks.useBulkReprocessEmails.mockReturnValue(noopMutation());
  mocks.useBulkDeleteIngestedEmails.mockReturnValue(noopMutation());
};

const renderPage = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <InboxPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
};

describe('InboxPage — reprocess-all-skipped controls', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
  });

  it('does not render the banner when there are no skipped emails', () => {
    setupHooks({ skippedCount: 0 });
    renderPage();
    expect(screen.queryByTestId('skipped-emails-banner')).toBeNull();
  });

  it('renders the banner when skipped emails exist and the user is not already on the skipped view', () => {
    setupHooks({ skippedCount: 5 });
    renderPage();

    const banner = screen.getByTestId('skipped-emails-banner');
    expect(banner).toBeInTheDocument();
    // The count is rendered as bold inside the banner body — the action button
    // also carries "5", so scope the text match to the banner *and* look for
    // the specific "5 emails were skipped" phrasing.
    expect(within(banner).getByText(/emails were skipped/i)).toBeInTheDocument();
    expect(within(banner).getByRole('button', { name: /Reprocess 5 skipped/i })).toBeInTheDocument();
  });

  it('clicking the banner action calls the reprocess-skipped mutation', async () => {
    setupHooks({ skippedCount: 3 });
    renderPage();

    const banner = screen.getByTestId('skipped-emails-banner');
    const button = within(banner).getByRole('button', { name: /Reprocess 3 skipped/i });
    fireEvent.click(button);

    await Promise.resolve();
    expect(mocks.reprocessMutate).toHaveBeenCalled();
  });

  it('dismissing the banner hides it and persists the dismissed count per tenant', () => {
    setupHooks({ skippedCount: 7 });
    const { unmount } = renderPage();

    const banner = screen.getByTestId('skipped-emails-banner');
    const dismiss = within(banner).getByLabelText(/Dismiss skipped emails banner/i);
    fireEvent.click(dismiss);

    expect(screen.queryByTestId('skipped-emails-banner')).toBeNull();
    expect(
      window.localStorage.getItem(`inbox.skippedBannerDismissedCount.${TENANT_ID}`),
    ).toBe('7');

    // Remount with the same skipped count — dismissed state should survive.
    unmount();
    setupHooks({ skippedCount: 7 });
    renderPage();
    expect(screen.queryByTestId('skipped-emails-banner')).toBeNull();
  });

  it('banner reappears when the skipped count grows past the dismissed count', () => {
    // Simulate a prior session that dismissed at 4.
    window.localStorage.setItem(`inbox.skippedBannerDismissedCount.${TENANT_ID}`, '4');
    setupHooks({ skippedCount: 9 });
    renderPage();

    const banner = screen.getByTestId('skipped-emails-banner');
    expect(banner).toBeInTheDocument();
    expect(within(banner).getByRole('button', { name: /Reprocess 9 skipped/i })).toBeInTheDocument();
  });

  it('shows the inline "Reprocess all" button inside the filter bar only on the Skipped view', () => {
    setupHooks({ skippedCount: 6 });
    renderPage();

    // showFilters auto-opens when there's data, so the pills are already
    // visible. On the default (All) view, the inline reprocess button is not
    // shown.
    expect(screen.queryByTestId('reprocess-all-skipped')).toBeNull();

    // Switch to Skipped by clicking the filter pill. The banner body also
    // contains the word "skipped", so scope the match to buttons that render
    // a standalone "Skipped" label plus a count badge (the filter pill text
    // collapses to "Skipped N" under accessible-name computation).
    const buttons = screen.getAllByRole('button', { name: /^Skipped\s+\d+$/i });
    expect(buttons.length).toBe(1);
    fireEvent.click(buttons[0]);

    const inlineButton = screen.getByTestId('reprocess-all-skipped');
    expect(inlineButton).toBeInTheDocument();
    expect(inlineButton).toHaveTextContent(/Reprocess 6 skipped/i);
  });
});
