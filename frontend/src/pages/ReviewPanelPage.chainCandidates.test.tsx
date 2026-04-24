/**
 * Chain-candidate panel tests — exercise the render + select flow in
 * isolation. Mounts the ReviewPanelPage with minimal hook mocks so the
 * candidate chips render, then simulates a reviewer clicking a chip and
 * asserts useAssignChainCandidate fires with the right payload.
 *
 * Rationale: ReviewPanelPage is a large component with many hooks; these
 * tests focus only on the chain-candidate UX introduced in this commit.
 * Broader coverage of the review page belongs in separate files.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { ReviewPanelPage } from './ReviewPanelPage';

const mocks = vi.hoisted(() => ({
  assignMutate: vi.fn(),
  useIngestionTimesheet: vi.fn(),
  useIngestionEmail: vi.fn(),
  useUsers: vi.fn(),
  useClients: vi.fn(),
  useProjects: vi.fn(),
  useIngestionTimesheets: vi.fn(),
  useFetchJobStatus: vi.fn(),
  useCreateClient: vi.fn(),
  noop: vi.fn(),
}));

vi.mock('@/hooks', () => {
  const mutation = (override?: { mutateAsync?: typeof vi.fn; isPending?: boolean }) => ({
    mutateAsync: override?.mutateAsync ?? vi.fn().mockResolvedValue(undefined),
    mutate: vi.fn(),
    isPending: override?.isPending ?? false,
  });
  return {
    useAddIngestionLineItem: () => mutation(),
    useApproveIngestionTimesheet: () => mutation(),
    useAssignChainCandidate: () => mutation({ mutateAsync: mocks.assignMutate }),
    useClients: mocks.useClients,
    useCreateClient: mocks.useCreateClient,
    useDeleteIngestionLineItem: () => mutation(),
    useDraftIngestionComment: () => mutation(),
    useFetchJobStatus: mocks.useFetchJobStatus,
    useHoldIngestionTimesheet: () => mutation(),
    useIngestionEmail: mocks.useIngestionEmail,
    useIngestionTimesheet: mocks.useIngestionTimesheet,
    useIngestionTimesheets: mocks.useIngestionTimesheets,
    useProjects: mocks.useProjects,
    useRejectIngestionLineItem: () => mutation(),
    useRejectIngestionTimesheet: () => mutation(),
    useReprocessIngestionEmail: () => mutation(),
    useRevertIngestionTimesheetRejection: () => mutation(),
    useUnrejectIngestionLineItem: () => mutation(),
    useUpdateIngestionLineItem: () => mutation(),
    useUpdateIngestionTimesheetData: () => mutation(),
    useUsers: mocks.useUsers,
  };
});

vi.mock('@/api/endpoints', () => ({
  ingestionAPI: {
    // ReviewPanelPage references this directly for attachment URLs.
    getAttachmentFileUrl: vi.fn(),
  },
}));

vi.mock('@/components', () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  Card: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardTitle: ({ children }: { children: React.ReactNode }) => <h3>{children}</h3>,
  Loading: ({ message }: { message: string }) => <div>{message}</div>,
  Modal: ({ open, children }: { open: boolean; children: React.ReactNode }) =>
    open ? <div>{children}</div> : null,
}));

const baseTimesheet = {
  id: 42,
  tenant_id: 1,
  attachment_id: null,
  status: 'pending',
  employee_id: null,
  employee_name: null,
  client_id: null,
  client_name: null,
  reviewer_id: null,
  period_start: null,
  period_end: null,
  total_hours: null,
  extracted_data: null,
  corrected_data: null,
  llm_anomalies: null,
  llm_summary: null,
  rejection_reason: null,
  internal_notes: null,
  submitted_at: null,
  reviewed_at: null,
  created_at: '2026-04-22T00:00:00Z',
  updated_at: '2026-04-22T00:00:00Z',
  time_entries_created: false,
  extracted_employee_name: null,
  extracted_supervisor_name: null,
  email: null,
  line_items: [],
  audit_log: [],
};

const setupHooks = (llmMatchSuggestions: Record<string, unknown> | null) => {
  mocks.useIngestionTimesheet.mockReturnValue({
    data: { ...baseTimesheet, llm_match_suggestions: llmMatchSuggestions },
    isLoading: false,
    refetch: vi.fn(),
  });
  mocks.useIngestionEmail.mockReturnValue({ data: null, isLoading: false });
  mocks.useUsers.mockReturnValue({ data: [] });
  mocks.useClients.mockReturnValue({ data: [] });
  mocks.useProjects.mockReturnValue({ data: [] });
  mocks.useIngestionTimesheets.mockReturnValue({ data: [], isLoading: false });
  mocks.useFetchJobStatus.mockReturnValue({ data: null });
  mocks.useCreateClient.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
};

const renderPage = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={['/ingestion/timesheet/42']}>
      <QueryClientProvider client={client}>
        <Routes>
          <Route path="/ingestion/timesheet/:timesheetId" element={<ReviewPanelPage />} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  );
};


describe('ReviewPanelPage — chain candidate panel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.assignMutate.mockResolvedValue({
      timesheet_id: 42,
      employee_id: 99,
      created_new_user: true,
    });
  });

  it('does not render the panel when there are no chain candidates', () => {
    setupHooks(null);
    renderPage();
    expect(screen.queryByTestId('chain-candidates-panel')).toBeNull();
  });

  it('renders one chip per chain candidate when suggestions include them', () => {
    setupHooks({
      chain_candidates: [
        { name: 'Jane Doe', email: 'jane@x.example', existing_user_id: null, matches_extracted_name: false },
        { name: 'John Doe', email: null, existing_user_id: null, matches_extracted_name: false },
      ],
    });
    renderPage();

    const panel = screen.getByTestId('chain-candidates-panel');
    const chips = within(panel).getAllByTestId('chain-candidate-chip');
    expect(chips).toHaveLength(2);
    expect(within(panel).getByText(/Jane Doe/)).toBeInTheDocument();
    expect(within(panel).getByText(/John Doe/)).toBeInTheDocument();
  });

  it('clicking a chip with an email submits immediately with name + email', async () => {
    setupHooks({
      chain_candidates: [
        { name: 'Jane Doe', email: 'jane@x.example', existing_user_id: null, matches_extracted_name: true },
      ],
    });
    renderPage();

    const panel = screen.getByTestId('chain-candidates-panel');
    const chipButton = within(panel).getByRole('button', { name: /Jane Doe/ });
    fireEvent.click(chipButton);

    await waitFor(() => {
      expect(mocks.assignMutate).toHaveBeenCalledWith({
        id: 42,
        data: { name: 'Jane Doe', email: 'jane@x.example' },
      });
    });
  });

  it('clicking a name-only chip opens an inline email input before submitting', async () => {
    setupHooks({
      chain_candidates: [
        { name: 'Daniel Gwilt', email: null, existing_user_id: null, matches_extracted_name: false },
      ],
    });
    renderPage();

    const panel = screen.getByTestId('chain-candidates-panel');
    const chipButton = within(panel).getByRole('button', { name: /Daniel Gwilt/ });
    fireEvent.click(chipButton);

    // No mutation yet — we need an email first.
    expect(mocks.assignMutate).not.toHaveBeenCalled();

    const emailInput = within(panel).getByPlaceholderText(/email@example.com/i);
    fireEvent.change(emailInput, { target: { value: 'daniel@new.example' } });
    const confirm = within(panel).getByRole('button', { name: /Confirm/i });
    fireEvent.click(confirm);

    await waitFor(() => {
      expect(mocks.assignMutate).toHaveBeenCalledWith({
        id: 42,
        data: { name: 'Daniel Gwilt', email: 'daniel@new.example' },
      });
    });
  });

  it('name-only chip with known existing user submits without inline email', async () => {
    setupHooks({
      chain_candidates: [
        { name: 'Jane Doe', email: null, existing_user_id: 7, matches_extracted_name: false },
      ],
    });
    renderPage();

    const panel = screen.getByTestId('chain-candidates-panel');
    const chipButton = within(panel).getByRole('button', { name: /Jane Doe/ });
    fireEvent.click(chipButton);

    await waitFor(() => {
      expect(mocks.assignMutate).toHaveBeenCalledWith({
        id: 42,
        data: { name: 'Jane Doe', email: null },
      });
    });
    // No inline email input shown — known-user path skips it.
    expect(within(panel).queryByPlaceholderText(/email@example.com/i)).toBeNull();
  });

  it('hides the panel once the timesheet is already bound to an employee', () => {
    mocks.useIngestionTimesheet.mockReturnValue({
      data: {
        ...baseTimesheet,
        employee_id: 99,
        llm_match_suggestions: {
          chain_candidates: [
            { name: 'Jane Doe', email: 'jane@x.example', existing_user_id: null, matches_extracted_name: false },
          ],
        },
      },
      isLoading: false,
      refetch: vi.fn(),
    });
    mocks.useIngestionEmail.mockReturnValue({ data: null, isLoading: false });
    mocks.useUsers.mockReturnValue({ data: [] });
    mocks.useClients.mockReturnValue({ data: [] });
    mocks.useProjects.mockReturnValue({ data: [] });
    mocks.useIngestionTimesheets.mockReturnValue({ data: [], isLoading: false });
    mocks.useFetchJobStatus.mockReturnValue({ data: null });
    mocks.useCreateClient.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });

    renderPage();
    expect(screen.queryByTestId('chain-candidates-panel')).toBeNull();
  });
});
