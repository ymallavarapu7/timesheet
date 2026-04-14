import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lock, Mail, Moon, Sun } from 'lucide-react';

import { Card, CardContent } from '@/components';
import { useAuth } from '@/hooks';
import { useTheme } from '@/contexts/ThemeContext';
import { NeuralPrismIcon } from '@/components/layout/AcufyLogo';

// Dev-only quick login — file is gitignored and only exists locally.
// Uses Vite's glob import so the build succeeds even when the file is absent.
const devModules = import.meta.glob('./DevQuickLogin.tsx');
const hasDevLogin = Object.keys(devModules).length > 0;

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
  const [DevQuickLogin, setDevQuickLogin] = useState<React.FC<{ isLoading: boolean; onQuickLogin: (email: string, password: string) => void }> | null>(null);
  const { login } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();

  useEffect(() => {
    if (hasDevLogin) {
      const loader = Object.values(devModules)[0];
      loader().then((mod) => {
        const m = mod as { default: typeof DevQuickLogin };
        setDevQuickLogin(() => m.default);
      }).catch(() => {});
    }
  }, []);

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

  const handleQuickLogin = async (quickEmail: string, quickPassword: string) => {
    setError('');
    setIsLoading(true);
    setEmail(quickEmail);
    setPassword(quickPassword);

    try {
      const user = await login(quickEmail, quickPassword);
      navigate(getPostLoginRoute(user.role));
    } catch (err) {
      const msg = getErrorMessage(err);
      setError(msg === 'EMAIL_NOT_VERIFIED' ? EMAIL_NOT_VERIFIED_MSG : msg);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background p-0">
      {/* Theme toggle - absolute top-right */}
      <button
        type="button"
        onClick={toggleTheme}
        className="absolute right-6 top-6 z-10 inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground"
        aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
      >
        {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>

      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[55%_45%]">
        {/* Left panel — Acufy branded */}
        <section className="relative hidden overflow-hidden p-14 lg:flex lg:flex-col lg:justify-between" style={{ background: 'linear-gradient(135deg, #0B1120 0%, #0F172A 40%, #1E293B 100%)' }}>
          {/* Animated grid bg */}
          <div
            className="absolute inset-0 opacity-40"
            style={{
              backgroundImage: 'linear-gradient(rgba(14,165,233,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(14,165,233,0.06) 1px, transparent 1px)',
              backgroundSize: '60px 60px',
              maskImage: 'radial-gradient(ellipse 70% 60% at 50% 40%, black 20%, transparent 70%)',
              WebkitMaskImage: 'radial-gradient(ellipse 70% 60% at 50% 40%, black 20%, transparent 70%)',
            }}
          />
          {/* Glow orb */}
          <div className="absolute -right-24 -top-24 h-[500px] w-[500px] animate-pulse rounded-full" style={{ background: 'radial-gradient(circle, rgba(14,165,233,0.15) 0%, transparent 60%)' }} />
          <div className="absolute -bottom-32 -left-24 h-[400px] w-[400px] animate-pulse rounded-full" style={{ background: 'radial-gradient(circle, rgba(20,184,166,0.1) 0%, transparent 60%)', animationDelay: '2s' }} />

          <div className="relative z-10">
            <div className="flex items-center gap-3">
              <NeuralPrismIcon size={48} />
              <div>
                <h1 className="text-[28px] font-bold text-white tracking-wide">
                  ACUFY<span className="ml-1 text-lg font-medium text-[#2DD4BF]">AI</span>
                </h1>
                <p className="mt-[-2px] text-[10px] font-medium uppercase tracking-[2.5px] text-slate-400">AI Powered Innovation</p>
              </div>
            </div>
            <div className="mt-2 h-[2px] w-40 rounded-full" style={{ background: 'linear-gradient(90deg, #0EA5E9, #06B6D4, #14B8A6, #2DD4BF)' }} />
            <p className="mt-6 max-w-md text-base leading-relaxed text-slate-400">
              Intelligent timesheet operations — tracking, ingestion, and approval workflows unified in one platform.
            </p>
          </div>

          {/* Bottom card */}
          <div className="relative z-10 rounded-xl border border-white/10 bg-white/5 p-5 backdrop-blur-sm">
            <p className="text-sm leading-relaxed text-white/80">
              Fast reviewer workflow, AI-powered ingestion, and role-based access in one workspace built for modern IT consulting teams.
            </p>
          </div>

          {/* Sparkle particles */}
          <div className="absolute right-20 top-32">
            <svg width="60" height="60" viewBox="0 0 60 60" xmlns="http://www.w3.org/2000/svg">
              <circle cx="10" cy="20" r="3" fill="#0EA5E9" opacity="0.7" />
              <circle cx="30" cy="10" r="2" fill="#14B8A6" opacity="0.6" />
              <circle cx="40" cy="30" r="2.5" fill="#2DD4BF" opacity="0.5" />
              <path d="M20 5 L22 0 L24 5 L29 7 L24 9 L22 14 L20 9 L15 7 Z" fill="#0EA5E9" opacity="0.6" />
              <path d="M45 18 L46.5 14 L48 18 L52 19.5 L48 21 L46.5 25 L45 21 L41 19.5 Z" fill="#2DD4BF" opacity="0.4" />
            </svg>
          </div>
        </section>

        {/* Right panel — login form */}
        <section className="flex items-center justify-center bg-card px-6 py-10">
          <Card className="w-full max-w-[420px] border-0 shadow-none">
            <CardContent className="p-0">
              <div className="mb-8">
                {/* Mobile logo */}
                <div className="mb-6 flex items-center gap-2 lg:hidden">
                  <NeuralPrismIcon size={32} />
                  <span className="text-lg font-bold text-foreground tracking-wide">
                    ACUFY<span className="ml-0.5 text-sm font-medium text-[#2DD4BF]">AI</span>
                  </span>
                </div>
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
                      placeholder="you@company.com"
                      className="field-input pl-11"
                      required
                    />
                  </div>
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

                {error && (
                  <div className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
                    {error}
                  </div>
                )}

                <button type="submit" disabled={isLoading} className="action-button w-full">
                  {isLoading ? 'Signing In...' : 'Sign In'}
                </button>
              </form>

              {/* Dev-only quick login — only renders if DevQuickLogin.tsx exists locally */}
              {DevQuickLogin && <DevQuickLogin isLoading={isLoading} onQuickLogin={handleQuickLogin} />}
            </CardContent>
          </Card>
        </section>
      </div>
    </div>
  );
};
