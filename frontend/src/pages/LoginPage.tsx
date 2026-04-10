import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lock, Mail } from 'lucide-react';

import { Card, CardContent } from '@/components';
import { useAuth } from '@/hooks';

type QuickLoginRole = 'admin' | 'ceo' | 'senior-manager' | 'manager' | 'employee';

const QUICK_LOGIN_USERS = {
  admin: [{ email: 'admin@example.com', password: 'password', name: 'Admin' }],
  ceo: [{ email: 'ceo@example.com', password: 'password', name: 'CEO' }],
  'senior-manager': [
    { email: 'margaret@example.com', password: 'password', name: 'Margaret' },
    { email: 'alexander@example.com', password: 'password', name: 'Alex' },
  ],
  manager: [
    { email: 'manager1@example.com', password: 'password', name: 'Manager 1' },
    { email: 'manager2@example.com', password: 'password', name: 'Manager 2' },
    { email: 'manager3@example.com', password: 'password', name: 'Manager 3' },
  ],
  employee: [
    { email: 'emp1-1@example.com', password: 'password', name: 'Employee 1' },
    { email: 'emp1-2@example.com', password: 'password', name: 'Employee 2' },
    { email: 'emp1-3@example.com', password: 'password', name: 'Employee 3' },
  ],
} as const;

const QUICK_LOGIN_ORDER: QuickLoginRole[] = ['admin', 'ceo', 'senior-manager', 'manager', 'employee'];

const getErrorMessage = (error: unknown): string => {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return 'Login failed';
};

const EMAIL_NOT_VERIFIED_MSG =
  'Your account has not been verified yet. Please check your email for the verification link.';

const getPostLoginRoute = (role?: string) => (role === 'PLATFORM_ADMIN' ? '/platform/tenants' : '/dashboard');

export const LoginPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const user = await login(email, password);
      navigate(getPostLoginRoute(user.role));
    } catch (err) {
      const msg = getErrorMessage(err);
      setError(msg === 'EMAIL_NOT_VERIFIED' ? EMAIL_NOT_VERIFIED_MSG : msg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleQuickLogin = async (role: QuickLoginRole) => {
    setError('');
    setIsLoading(true);

    try {
      for (const candidate of QUICK_LOGIN_USERS[role]) {
        try {
          setEmail(candidate.email);
          setPassword(candidate.password);
          const user = await login(candidate.email, candidate.password);
          navigate(getPostLoginRoute(user.role));
          return;
        } catch {
          continue;
        }
      }
      setError(`No seeded ${role.replace('-', ' ')} account is currently available.`);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background p-0">
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[55%_45%]">
        <section className="relative hidden overflow-hidden bg-[linear-gradient(135deg,#1E3A8A_0%,#2563EB_100%)] p-14 lg:flex lg:flex-col lg:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true">
                <path d="M10 6h20l10 14-10 14H10L0 20 10 6z" fill="white" fillOpacity="0.95" />
              </svg>
              <h1 className="text-[32px] font-bold text-white">TimesheetIQ</h1>
            </div>
            <p className="mt-5 text-base text-white/80">Time tracking and ingestion, unified.</p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/5 p-5">
            <p className="text-sm text-white/85">Fast reviewer workflow, ingestion controls, and role-based access in one light operational workspace.</p>
          </div>
        </section>

        <section className="flex items-center justify-center bg-card px-6 py-10">
          <Card className="w-full max-w-[420px] shadow-none">
            <CardContent className="p-0">
              <div className="mb-8">
                <h2 className="text-2xl font-semibold tracking-tight text-foreground">Welcome</h2>
                <p className="mt-2 text-sm text-muted-foreground">Sign in to your account</p>
              </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label className="mb-2 block text-sm font-medium text-foreground">Email</label>
                <div className="relative">
                  <Mail className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="admin@example.com"
                    className="field-input pl-11"
                    required
                  />
                </div>
                {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-foreground">Password</label>
                <div className="relative">
                  <Lock className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="********"
                    className="field-input pl-11"
                    required
                  />
                </div>
              </div>

              <button type="submit" disabled={isLoading} className="action-button w-full">
                {isLoading ? 'Signing In...' : 'Sign In'}
              </button>
            </form>

            <div className="mt-8 space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-foreground">Quick Login</p>
                <p className="text-xs text-muted-foreground">Testing</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {QUICK_LOGIN_ORDER.map((role) => (
                  <button
                    key={role}
                    type="button"
                    disabled={isLoading}
                    onClick={() => handleQuickLogin(role)}
                    className="rounded-md bg-muted px-4 py-2 text-left text-sm font-medium text-foreground transition hover:bg-slate-200 disabled:opacity-50"
                  >
                    {role.replace('-', ' ')}
                  </button>
                ))}
              </div>
            </div>
            </CardContent>
          </Card>
        </section>
      </div>
    </div>
  );
};

