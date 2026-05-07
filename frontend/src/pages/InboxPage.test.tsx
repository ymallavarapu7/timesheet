import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import {
  InboxPage,
  STALE_BUSINESS_DAYS,
  domainOf,
  formatRelativeReceived,
  getInitials,
  isPersonalDomain,
  isStaleReceived,
  suggestNameFromDomain,
} from './InboxPage';
import type { IngestionTimesheetSummary } from '@/types';

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  useBulkReprocessEmails: vi.fn(),
  useBulkDeleteIngestedEmails: vi.fn(),
  useClients: vi.fn(),
  useCreateClientFromDomain: vi.fn(),
  useDeleteIngestedEmail: vi.fn(),
  useFetchJobStatus: vi.fn(),
  useIngestionTimesheets: vi.fn(),
  useMailboxes: vi.fn(),
  useReprocessIngestionEmail: vi.fn(),
  useReprocessSkippedEmails: vi.fn(),
  useSkippedEmails: vi.fn(),
  useTriggerFetchEmails: vi.fn(),
  reprocessMutate: vi.fn(),
  cascadeMutate: vi.fn(),
}));

vi.mock('@/hooks', () => ({
  useAuth: mocks.useAuth,
  useBulkReprocessEmails: mocks.useBulkReprocessEmails,
  useBulkDeleteIngestedEmails: mocks.useBulkDeleteIngestedEmails,
  useClients: mocks.useClients,
  useCreateClientFromDomain: mocks.useCreateClientFromDomain,
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
  llm_match_suggestions: null,
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
  mocks.useCreateClientFromDomain.mockReturnValue({
    mutateAsync: mocks.cascadeMutate.mockResolvedValue({
      client: { id: 99, name: 'DXC Technology' },
      domain: 'dxc.com',
      cascaded_count: 0,
    }),
    mutate: vi.fn(),
    isPending: false,
  });
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

// ───────────────────────────────────────────────────────────────────────
// Inbox redesign helpers (per-cell attention + relative time + initials)
// ───────────────────────────────────────────────────────────────────────

describe('getInitials', () => {
  it('returns first+last initial for "Last, First" form', () => {
    expect(getInitials('Rajendran, R.')).toBe('RR');
    expect(getInitials('Davis, Amanda')).toBe('AD');
  });
  it('returns first+last initial for "First Last" form', () => {
    expect(getInitials('Sarah Lee')).toBe('SL');
    expect(getInitials('Mike Garcia')).toBe('MG');
  });
  it('returns the first two characters for a single name', () => {
    expect(getInitials('Acuent')).toBe('AC');
  });
  it('falls back to email local-part when name is empty', () => {
    expect(getInitials(null, 'r.rajendran3@dxc.com')).toBe('R.');
    expect(getInitials('', 'admin@example.com')).toBe('AD');
  });
  it('returns ? when nothing usable is available', () => {
    expect(getInitials(null, null)).toBe('?');
    expect(getInitials('', '')).toBe('?');
  });
});

describe('domainOf and isPersonalDomain', () => {
  it('extracts the lowercased bare domain from an email', () => {
    expect(domainOf('Foo@DXC.com')).toBe('dxc.com');
    expect(domainOf('alice@aegon.com')).toBe('aegon.com');
  });
  it('returns "" for malformed input', () => {
    expect(domainOf('')).toBe('');
    expect(domainOf(null)).toBe('');
    expect(domainOf('not-an-email')).toBe('');
  });
  it('flags canonical personal email providers', () => {
    expect(isPersonalDomain('gmail.com')).toBe(true);
    expect(isPersonalDomain('GMAIL.COM')).toBe(true);
    expect(isPersonalDomain('outlook.com')).toBe(true);
    expect(isPersonalDomain('proton.me')).toBe(true);
  });
  it('does not flag real client domains', () => {
    expect(isPersonalDomain('dxc.com')).toBe(false);
    expect(isPersonalDomain('aegon.com')).toBe(false);
  });
});

describe('suggestNameFromDomain', () => {
  it('uppercases short stems', () => {
    expect(suggestNameFromDomain('dxc.com')).toBe('DXC');
    expect(suggestNameFromDomain('ibm.com')).toBe('IBM');
  });
  it('title-cases longer stems', () => {
    expect(suggestNameFromDomain('aegon.com')).toBe('Aegon');
    expect(suggestNameFromDomain('accenture.com')).toBe('Accenture');
  });
  it('returns "" for empty input', () => {
    expect(suggestNameFromDomain('')).toBe('');
  });
});

describe('formatRelativeReceived', () => {
  it('returns "--" for empty input', () => {
    expect(formatRelativeReceived(null)).toBe('--');
    expect(formatRelativeReceived(undefined)).toBe('--');
    expect(formatRelativeReceived('')).toBe('--');
  });
  it('formats minutes/hours/days correctly', () => {
    const now = Date.now();
    expect(formatRelativeReceived(new Date(now - 30_000).toISOString())).toMatch(/Just now/);
    expect(formatRelativeReceived(new Date(now - 5 * 60_000).toISOString())).toBe('5m ago');
    expect(formatRelativeReceived(new Date(now - 3 * 60 * 60_000).toISOString())).toBe('3h ago');
    expect(formatRelativeReceived(new Date(now - 26 * 60 * 60_000).toISOString())).toBe('Yesterday');
    expect(formatRelativeReceived(new Date(now - 3 * 24 * 60 * 60_000).toISOString())).toBe('3d ago');
  });
  it('falls back to absolute date past one week', () => {
    const eightDaysAgo = new Date(Date.now() - 8 * 24 * 60 * 60_000).toISOString();
    const out = formatRelativeReceived(eightDaysAgo);
    // Localized; we just check it does not match the 'Nd ago' or 'Yesterday' patterns.
    expect(out).not.toBe('--');
    expect(out).not.toMatch(/^\d+d ago$/);
    expect(out).not.toBe('Yesterday');
  });
});

describe('isStaleReceived', () => {
  it('returns false for fresh timestamps', () => {
    const now = new Date().toISOString();
    expect(isStaleReceived(now)).toBe(false);
    const yesterday = new Date(Date.now() - 24 * 60 * 60_000).toISOString();
    expect(isStaleReceived(yesterday)).toBe(false);
  });
  it('returns true for timestamps older than the stale threshold', () => {
    // 12 calendar days ago is well past 5 business days, regardless of weekend math.
    const twelveDaysAgo = new Date(Date.now() - 12 * 24 * 60 * 60_000).toISOString();
    expect(isStaleReceived(twelveDaysAgo)).toBe(true);
  });
  it('returns false for empty input', () => {
    expect(isStaleReceived(null)).toBe(false);
    expect(isStaleReceived('')).toBe(false);
  });
  it('exports a documented threshold constant', () => {
    expect(STALE_BUSINESS_DAYS).toBeGreaterThan(0);
  });
});

// ───────────────────────────────────────────────────────────────────────
// Inbox table layout regression
// ───────────────────────────────────────────────────────────────────────

describe('InboxPage — table layout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  const renderWithRow = (overrides: Partial<IngestionTimesheetSummary> = {}) => {
    const row = makeSkippedSummary({
      id: 1,
      email_id: 1000,
      status: 'pending',
      subject: 'Weekly timesheet',
      sender_name: 'Rajendran, R.',
      sender_email: 'r.rajendran3@dxc.com',
      received_at: new Date(Date.now() - 2 * 60 * 60_000).toISOString(),
      ...overrides,
    });
    setupHooks({ skippedCount: 0 });
    mocks.useIngestionTimesheets.mockReturnValue({ data: [row], isLoading: false });
    renderPage();
  };

  it('does not render an "AI Flags" column header', () => {
    renderWithRow();
    expect(screen.queryByRole('columnheader', { name: /AI Flags/i })).toBeNull();
  });

  it('renders Sender, Subject, Client, Employee, Week, Hours, Status, Received, Actions', () => {
    renderWithRow();
    for (const name of ['Sender', 'Subject', 'Client', 'Employee', 'Week', 'Hours', 'Status', 'Received', 'Actions']) {
      expect(screen.getByRole('columnheader', { name: new RegExp(`^${name}$`, 'i') })).toBeInTheDocument();
    }
  });

  it('shows the inline "Create from <domain>" cascade button when no client is assigned and the sender is on a real domain', () => {
    renderWithRow({ client_name: null, sender_email: 'r.rajendran3@dxc.com' });
    const button = screen.getByRole('button', { name: /Create from\s+dxc\.com/i });
    expect(button).toBeInTheDocument();
  });

  it('shows the static "Needs client" pill on personal-domain rows (no cascade is possible)', () => {
    renderWithRow({ client_name: null, sender_email: 'forwarder@gmail.com' });
    expect(screen.getByText(/Needs client/i)).toBeInTheDocument();
    // And the Create-from button is suppressed.
    expect(screen.queryByRole('button', { name: /Create from\s+gmail\.com/i })).toBeNull();
  });

  it('shows "Needs employee" amber pill when no employee is assigned', () => {
    renderWithRow({
      client_name: null,
      employee_name: null,
      extracted_employee_name: null,
    });
    expect(screen.getByText(/Needs employee/i)).toBeInTheDocument();
  });

  it('opens the cascade popover when the inline create button is clicked', () => {
    renderWithRow({ client_name: null, sender_email: 'alice@dxc.com' });
    const button = screen.getByRole('button', { name: /Create from\s+dxc\.com/i });
    fireEvent.click(button);

    // The popover renders as a dialog with the matching aria-label.
    expect(screen.getByRole('dialog', { name: /Assign client from domain/i })).toBeInTheDocument();
    // The pre-filled input contains the smart-guess derived from the domain.
    const input = screen.getByLabelText(/Client name/i) as HTMLInputElement;
    expect(input.value).toBe('DXC');
    // The primary button shows the "Create" label since no existing client matches.
    expect(screen.getByRole('button', { name: /Create "DXC"/i })).toBeInTheDocument();
  });
});
