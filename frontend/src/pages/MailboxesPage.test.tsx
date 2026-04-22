import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MailboxesPage } from './MailboxesPage';
import type { Mailbox } from '@/types';

const mocks = vi.hoisted(() => ({
  useMailboxes: vi.fn(),
  useAuth: vi.fn(),
  useClients: vi.fn(),
  useCreateMailbox: vi.fn(),
  useUpdateMailbox: vi.fn(),
  useDeleteMailbox: vi.fn(),
  useTestMailbox: vi.fn(),
  useResetMailboxCursor: vi.fn(),
  useTenantSettings: vi.fn(),
  useUpdateTenantSettings: vi.fn(),
  oauthConnect: vi.fn(),
}));

vi.mock('@/hooks', () => ({
  useMailboxes: mocks.useMailboxes,
  useAuth: mocks.useAuth,
  useClients: mocks.useClients,
  useCreateMailbox: mocks.useCreateMailbox,
  useUpdateMailbox: mocks.useUpdateMailbox,
  useDeleteMailbox: mocks.useDeleteMailbox,
  useTestMailbox: mocks.useTestMailbox,
  useResetMailboxCursor: mocks.useResetMailboxCursor,
  useTenantSettings: mocks.useTenantSettings,
  useUpdateTenantSettings: mocks.useUpdateTenantSettings,
}));

vi.mock('@/api/endpoints', () => ({
  mailboxesAPI: {
    oauthConnect: mocks.oauthConnect,
  },
}));

vi.mock('@/api/client', () => ({
  apiClient: { defaults: { baseURL: 'http://localhost:8000' } },
}));

vi.mock('@/components', () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  Card: ({ children }: { children: React.ReactNode }) => <div data-testid="mailbox-card">{children}</div>,
  CardContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardDescription: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardTitle: ({ children }: { children: React.ReactNode }) => <h3>{children}</h3>,
  EmptyState: ({ message }: { message: string }) => <div>{message}</div>,
  Loading: ({ message }: { message: string }) => <div>{message}</div>,
}));

const makeMailbox = (overrides: Partial<Mailbox>): Mailbox => ({
  id: 1,
  tenant_id: 1,
  label: 'Mailbox',
  protocol: 'imap',
  auth_type: 'basic',
  host: 'imap.example.com',
  port: 993,
  use_ssl: true,
  username: 'user@example.com',
  has_password: true,
  oauth_provider: null,
  oauth_email: null,
  smtp_host: null,
  smtp_port: null,
  smtp_username: null,
  linked_client_id: null,
  is_active: true,
  last_fetched_at: null,
  created_at: '2026-04-01T00:00:00Z',
  updated_at: '2026-04-01T00:00:00Z',
  ...overrides,
});

const setupHooks = (mailboxes: Mailbox[]) => {
  mocks.useMailboxes.mockReturnValue({
    data: mailboxes,
    isLoading: false,
    refetch: vi.fn(),
  });
  mocks.useAuth.mockReturnValue({ tenant: { max_mailboxes: 10 } });
  mocks.useClients.mockReturnValue({ data: [] });
  const noopMutation = { mutateAsync: vi.fn().mockResolvedValue(undefined), mutate: vi.fn(), isPending: false };
  mocks.useCreateMailbox.mockReturnValue(noopMutation);
  mocks.useUpdateMailbox.mockReturnValue(noopMutation);
  mocks.useDeleteMailbox.mockReturnValue(noopMutation);
  mocks.useTestMailbox.mockReturnValue(noopMutation);
  mocks.useResetMailboxCursor.mockReturnValue(noopMutation);
  mocks.useTenantSettings.mockReturnValue({ data: {} });
  mocks.useUpdateTenantSettings.mockReturnValue(noopMutation);
};

describe('MailboxesPage — Reconnect action', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.oauthConnect.mockResolvedValue({ data: { auth_url: 'https://accounts.google.com/oauth' } });
    vi.spyOn(window, 'open').mockImplementation(() => null);
  });

  it('shows a Reconnect button on OAuth mailbox rows', () => {
    setupHooks([
      makeMailbox({
        id: 42,
        label: 'Google Workspace - tenantuser7@gmail.com',
        auth_type: 'oauth2',
        oauth_provider: 'google',
        oauth_email: 'tenantuser7@gmail.com',
      }),
    ]);

    render(<MailboxesPage />);

    const card = screen.getByRole('heading', { name: /Google Workspace/ }).closest('[data-testid="mailbox-card"]');
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByRole('button', { name: /Reconnect/i })).toBeInTheDocument();
  });

  it('does not show a Reconnect button on basic-auth mailbox rows', () => {
    setupHooks([
      makeMailbox({
        id: 7,
        label: 'Legacy IMAP',
        auth_type: 'basic',
        oauth_provider: null,
      }),
    ]);

    render(<MailboxesPage />);

    const card = screen.getByRole('heading', { name: /Legacy IMAP/ }).closest('[data-testid="mailbox-card"]');
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).queryByRole('button', { name: /Reconnect/i })).toBeNull();
  });

  it('calls the OAuth connect endpoint with the mailbox provider when Reconnect is clicked', async () => {
    setupHooks([
      makeMailbox({
        id: 42,
        label: 'Google Workspace - tenantuser7@gmail.com',
        auth_type: 'oauth2',
        oauth_provider: 'google',
        oauth_email: 'tenantuser7@gmail.com',
      }),
    ]);

    render(<MailboxesPage />);

    const reconnectButton = screen.getByRole('button', { name: /Reconnect/i });
    fireEvent.click(reconnectButton);

    // Wait a tick for the promise chain in handleOAuthConnect.
    await Promise.resolve();
    await Promise.resolve();

    expect(mocks.oauthConnect).toHaveBeenCalledWith('google');
    expect(window.open).toHaveBeenCalledWith(
      'https://accounts.google.com/oauth',
      'mailbox-oauth',
      expect.stringContaining('popup'),
    );
  });

  it('Reconnect stays enabled even when the tenant is at the mailbox cap', () => {
    // atCap gates "Connect Google / Connect Microsoft" for new mailboxes, but
    // Reconnect re-authorizes an existing OAuth record and must not be gated.
    mocks.useMailboxes.mockReturnValue({
      data: [
        makeMailbox({
          id: 1,
          label: 'Google Workspace - a@example.com',
          auth_type: 'oauth2',
          oauth_provider: 'google',
          oauth_email: 'a@example.com',
        }),
      ],
      isLoading: false,
      refetch: vi.fn(),
    });
    mocks.useAuth.mockReturnValue({ tenant: { max_mailboxes: 1 } });
    mocks.useClients.mockReturnValue({ data: [] });
    const noopMutation = { mutateAsync: vi.fn(), mutate: vi.fn(), isPending: false };
    mocks.useCreateMailbox.mockReturnValue(noopMutation);
    mocks.useUpdateMailbox.mockReturnValue(noopMutation);
    mocks.useDeleteMailbox.mockReturnValue(noopMutation);
    mocks.useTestMailbox.mockReturnValue(noopMutation);
    mocks.useResetMailboxCursor.mockReturnValue(noopMutation);
    mocks.useTenantSettings.mockReturnValue({ data: {} });
    mocks.useUpdateTenantSettings.mockReturnValue(noopMutation);

    render(<MailboxesPage />);

    const reconnectButton = screen.getByRole('button', { name: /Reconnect/i });
    expect(reconnectButton).not.toBeDisabled();

    // Sanity: the bottom "Connect Google" button *is* disabled at cap.
    const connectGoogle = screen.getByRole('button', { name: /Connect Google/i });
    expect(connectGoogle).toBeDisabled();
  });
});
