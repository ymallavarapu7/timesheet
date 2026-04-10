import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { LoginPage } from './LoginPage';

const mockLogin = vi.fn();
const mockNavigate = vi.fn();

vi.mock('@/hooks', () => ({
  useAuth: () => ({ login: mockLogin }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('@/components', () => ({
  Card: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  ),
  CardContent: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  ),
}));

const renderLogin = () =>
  render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders all quick login buttons', () => {
    renderLogin();
    expect(screen.getByRole('button', { name: /^admin$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^ceo$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /senior manager/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^manager$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^employee$/i })).toBeInTheDocument();
  });

  it('does not render a platform-admin quick login button', () => {
    renderLogin();
    expect(screen.queryByRole('button', { name: /platform/i })).not.toBeInTheDocument();
  });

  it('quick login admin calls login with correct credentials and navigates', async () => {
    mockLogin.mockResolvedValueOnce({ role: 'ADMIN' });
    renderLogin();

    fireEvent.click(screen.getByRole('button', { name: /^admin$/i }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('admin@example.com', 'password');
    });
    expect(mockNavigate).toHaveBeenCalledWith('/dashboard');
  });

  it('quick login ceo calls login with correct credentials', async () => {
    mockLogin.mockResolvedValueOnce({ role: 'CEO' });
    renderLogin();

    fireEvent.click(screen.getByRole('button', { name: /^ceo$/i }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('ceo@example.com', 'password');
    });
    expect(mockNavigate).toHaveBeenCalledWith('/dashboard');
  });

  it('quick login senior-manager tries first candidate (margaret)', async () => {
    mockLogin.mockResolvedValueOnce({ role: 'SENIOR_MANAGER' });
    renderLogin();

    fireEvent.click(screen.getByRole('button', { name: /senior manager/i }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('margaret@example.com', 'password');
    });
  });

  it('quick login manager tries first candidate (manager1)', async () => {
    mockLogin.mockResolvedValueOnce({ role: 'MANAGER' });
    renderLogin();

    fireEvent.click(screen.getByRole('button', { name: /^manager$/i }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('manager1@example.com', 'password');
    });
  });

  it('quick login employee tries first candidate (emp1-1)', async () => {
    mockLogin.mockResolvedValueOnce({ role: 'EMPLOYEE' });
    renderLogin();

    fireEvent.click(screen.getByRole('button', { name: /^employee$/i }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('emp1-1@example.com', 'password');
    });
  });

  it('falls back to next candidate when first login fails', async () => {
    mockLogin
      .mockRejectedValueOnce(new Error('Invalid'))
      .mockResolvedValueOnce({ role: 'MANAGER' });
    renderLogin();

    fireEvent.click(screen.getByRole('button', { name: /^manager$/i }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledTimes(2);
    });
    expect(mockLogin).toHaveBeenNthCalledWith(1, 'manager1@example.com', 'password');
    expect(mockLogin).toHaveBeenNthCalledWith(2, 'manager2@example.com', 'password');
    expect(mockNavigate).toHaveBeenCalledWith('/dashboard');
  });

  it('shows error when all candidates fail', async () => {
    mockLogin.mockRejectedValue(new Error('Invalid'));
    renderLogin();

    fireEvent.click(screen.getByRole('button', { name: /^employee$/i }));

    await waitFor(() => {
      expect(screen.getByText(/no seeded employee account/i)).toBeInTheDocument();
    });
  });

  it('manual login form works', async () => {
    mockLogin.mockResolvedValueOnce({ role: 'EMPLOYEE' });
    renderLogin();

    fireEvent.change(screen.getByPlaceholderText('admin@example.com'), {
      target: { value: 'test@example.com' },
    });
    fireEvent.change(screen.getByPlaceholderText('********'), {
      target: { value: 'mypass' },
    });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('test@example.com', 'mypass');
    });
  });
});
