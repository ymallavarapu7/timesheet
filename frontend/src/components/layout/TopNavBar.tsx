import React, { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  Bell,
  Check,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  LogOut,
  Menu,
  User as UserIcon,
  X,
} from 'lucide-react';

import { authAPI } from '@/api/endpoints';

import { AcufyLogo, NeuralPrismIcon } from '@/components/layout/AcufyLogo';
import { ThemePicker } from '@/components/layout/ThemePicker';
import { TopbarTimer } from '@/components/timer/TopbarTimer';
import { buildNavigation } from '@/components/layout/navigation';
import { cn } from '@/lib/utils';
import { useAuth, useIngestionEnabled, useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications } from '@/hooks';
import type { NavSection } from '@/components/layout/navigation';
import type { UserRole } from '@/types';

// New-tab role handoff: single-use token to /login?role-handoff=<token>.
const PORTAL_LABEL: Partial<Record<UserRole, string>> = {
  ADMIN: 'Admin',
  MANAGER: 'Manager',
  VIEWER: 'Viewer',
  EMPLOYEE: 'Employee',
};

const SwitchPortalChip: React.FC<{ targetRole: UserRole }> = ({ targetRole }) => {
  const [pending, setPending] = useState(false);
  const label = PORTAL_LABEL[targetRole] ?? targetRole;

  const handleClick = async () => {
    if (pending) return;
    setPending(true);
    try {
      const res = await authAPI.roleHandoffIssue(targetRole);
      const token = res.data.handoff_token;
      // Open in a new tab so the current session keeps running. The
      // login page reads ?role-handoff=... and exchanges it inside
      // the new tab's sessionStorage. noopener prevents the new tab
      // from referencing window.opener and tampering with our state.
      window.open(`/login?role-handoff=${encodeURIComponent(token)}`, '_blank', 'noopener');
    } catch (err) {
      console.error('Role handoff failed', err);
    } finally {
      setPending(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={pending}
      className="hidden md:inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition hover:bg-primary/20 disabled:opacity-60"
      title={`Open the ${label} portal in a new tab`}
    >
      <ExternalLink className="h-3.5 w-3.5" />
      Switch to {label}
    </button>
  );
};

/* ── Small helper: renders a single nav link (no dropdown) ── */
const SingleNavLink: React.FC<{ to: string; label: string; onClick?: () => void }> = ({ to, label, onClick }) => {
  const location = useLocation();
  const isActive = location.pathname === to;
  return (
    <NavLink
      to={to}
      onClick={onClick}
      className={cn(
        'rounded-lg px-3.5 py-1.5 text-[13px] font-medium transition',
        isActive
          ? 'bg-primary/15 text-primary'
          : 'text-muted-foreground hover:text-foreground',
      )}
    >
      {label}
    </NavLink>
  );
};

/* ── Dropdown for sections with multiple items ── */
const NavDropdown: React.FC<{ section: NavSection; onNavigate?: () => void }> = ({ section, onNavigate }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const hasActiveChild = section.items.some(
    (item) =>
      location.pathname === item.to ||
      item.match?.some((m) => location.pathname.startsWith(m)),
  );

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'inline-flex items-center gap-1 rounded-lg px-3.5 py-1.5 text-[13px] font-medium transition',
          hasActiveChild
            ? 'bg-primary/15 text-primary'
            : 'text-muted-foreground hover:text-foreground',
        )}
      >
        {section.title}
        <ChevronDown className={cn('h-3 w-3 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1.5 min-w-[180px] rounded-xl border border-border bg-card p-1.5 shadow-[0_12px_36px_rgba(0,0,0,0.12)]">
          {section.items.map((item) => {
            const Icon = item.icon;
            const isActive =
              location.pathname === item.to ||
              item.match?.some((m) => location.pathname.startsWith(m)) ||
              false;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => {
                  setOpen(false);
                  onNavigate?.();
                }}
                className={cn(
                  'flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition',
                  isActive
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground',
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {item.label}
              </NavLink>
            );
          })}
        </div>
      )}
    </div>
  );
};

/* ══════════════════════════════════════════════════════════════
   Main TopNavBar
   ══════════════════════════════════════════════════════════════ */
export const TopNavBar: React.FC = () => {
  const navigate = useNavigate();
  const { user, tenant, logout } = useAuth();
  const ingestionEnabled = useIngestionEnabled();
  const sections = buildNavigation(user, ingestionEnabled);

  const { data: notifications } = useNotifications();
  const markNotificationRead = useMarkNotificationRead();
  const markAllNotificationsRead = useMarkAllNotificationsRead();
  const totalCount = notifications?.total_count ?? 0;

  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const notificationsRef = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);

  const initials = (user?.full_name || 'U')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((chunk) => chunk[0]?.toUpperCase())
    .join('');

  // Close dropdowns on outside click / Escape
  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (notificationsRef.current && !notificationsRef.current.contains(target)) setNotificationsOpen(false);
      if (profileRef.current && !profileRef.current.contains(target)) setProfileOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setNotificationsOpen(false);
        setProfileOpen(false);
        setMobileMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  const getSeverityClasses = (severity: string) => {
    if (severity === 'error') return 'bg-red-500/15 text-red-500 dark:text-red-400';
    if (severity === 'warning') return 'bg-amber-500/15 text-amber-600 dark:text-amber-400';
    if (severity === 'success') return 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400';
    return 'bg-sky-500/15 text-sky-600 dark:text-sky-400';
  };

  const getSeverityLabel = (severity: string) => {
    if (severity === 'error') return 'Alert';
    if (severity === 'warning') return 'Notice';
    if (severity === 'success') return 'Done';
    return 'Info';
  };

  const handleNotificationClick = async (notificationId: string, route: string) => {
    try { await markNotificationRead.mutateAsync(notificationId); } catch { /* ignore */ }
    setNotificationsOpen(false);
    navigate(route || '/dashboard');
  };

  const handleMarkRead = async (e: React.MouseEvent, notificationId: string) => {
    e.stopPropagation();
    try { await markNotificationRead.mutateAsync(notificationId); } catch { /* ignore */ }
  };

  /* ── Flatten sections for rendering ──
     Workspace is always rendered inline (it's the user's primary navigation;
     a dropdown for 2-4 items adds a click for no gain). Other sections stay
     collapsed in a dropdown. */
  const renderNavItems = (onNavigate?: () => void) =>
    sections.flatMap((section) => {
      if (section.items.length === 1 || section.title === 'Workspace') {
        return section.items.map((item) => (
          <SingleNavLink key={item.to} to={item.to} label={item.label} onClick={onNavigate} />
        ));
      }
      return [<NavDropdown key={section.title} section={section} onNavigate={onNavigate} />];
    });

  return (
    <>
      <nav
        className="sticky top-0 z-50 border-b bg-card/90 backdrop-blur-xl"
        style={{ borderColor: 'var(--glass-border)' }}
      >
        <div className="mx-auto flex h-[76px] max-w-[1800px] items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          {/* ── Left: Logo ── */}
          <Link to="/dashboard" className="shrink-0">
            <AcufyLogo variant="full" />
          </Link>

          {/* ── Center: Navigation links (desktop) ── */}
          <div className="hidden items-center gap-1 lg:flex">
            {renderNavItems()}
          </div>

          {/* ── Right: theme + notifications + profile ── */}
          <div className="flex items-center gap-2">
            {/* Tenant / organization name */}
            {tenant?.name && (
              <span className="hidden whitespace-nowrap text-sm font-medium text-foreground md:inline-block">
                {tenant.name}
              </span>
            )}

            {/* Multi-role users: switch active role via /auth/switch-role. */}
            {user?.roles && user.roles.length > 1 && (() => {
              const target = user.roles.find((r) => r !== user.role);
              return target ? <SwitchPortalChip targetRole={target} /> : null;
            })()}

            <div className="hidden sm:block mr-2">
              <TopbarTimer />
            </div>

            {/* Theme picker */}
            <ThemePicker />

            {/* Notifications */}
            <div ref={notificationsRef} className="relative">
              <button
                type="button"
                onClick={() => { setNotificationsOpen((v) => !v); setProfileOpen(false); }}
                className="relative inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground"
                aria-label="Notifications"
              >
                <Bell className="h-4 w-4" />
                {totalCount > 0 && (
                  <span className="absolute -right-1 -top-1 inline-flex min-h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-white">
                    {totalCount > 99 ? '99+' : totalCount}
                  </span>
                )}
              </button>
              {notificationsOpen && (
                <div className="absolute right-0 top-11 z-50 w-[360px] rounded-2xl border border-border bg-card p-2 shadow-[0_18px_40px_rgba(0,0,0,0.15)]">
                  <div className="flex items-center justify-between px-3 py-2">
                    <div>
                      <p className="text-sm font-semibold text-foreground">Notifications</p>
                      <p className="text-xs text-muted-foreground">{totalCount} unread</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => markAllNotificationsRead.mutate()}
                      className="text-xs font-medium text-primary transition hover:text-primary/80 disabled:opacity-50"
                      disabled={totalCount === 0 || markAllNotificationsRead.isPending}
                    >
                      Mark all read
                    </button>
                  </div>
                  <div className="max-h-[420px] overflow-y-auto py-1">
                    {(notifications?.items ?? []).length === 0 ? (
                      <div className="px-3 py-8 text-center text-sm text-muted-foreground">No notifications.</div>
                    ) : (
                      (notifications?.items ?? []).map((item) => (
                        <div key={item.id} className="group relative flex items-start gap-3 rounded-xl px-3 py-3 transition hover:bg-muted/50">
                          <button
                            type="button"
                            onClick={() => void handleNotificationClick(item.id, item.route)}
                            className="flex min-w-0 flex-1 items-start gap-3 text-left"
                          >
                            <span className={cn('mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase', getSeverityClasses(item.severity))}>
                              {getSeverityLabel(item.severity)}
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-start gap-2">
                                <p className="truncate text-sm font-medium text-foreground" title={item.title}>{item.title}</p>
                                {!item.is_read && <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-primary" />}
                              </div>
                              <p className="mt-1 line-clamp-2 text-xs text-muted-foreground" title={item.message}>{item.message}</p>
                            </div>
                            <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                          </button>
                          {!item.is_read && (
                            <button
                              type="button"
                              onClick={(e) => void handleMarkRead(e, item.id)}
                              className="absolute right-2 top-2 hidden h-5 w-5 items-center justify-center rounded-full bg-muted text-muted-foreground transition hover:bg-primary hover:text-white group-hover:flex"
                              title="Mark as read"
                            >
                              <Check className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Profile avatar + dropdown */}
            <div ref={profileRef} className="relative">
              <button
                type="button"
                onClick={() => { setProfileOpen((v) => !v); setNotificationsOpen(false); }}
                className="inline-flex h-8 w-8 items-center justify-center rounded-full text-[11px] font-bold text-white transition hover:opacity-85"
                style={{ background: 'linear-gradient(135deg, #0EA5E9, #14B8A6)' }}
                aria-label="Profile"
              >
                {initials}
              </button>
              {profileOpen && (
                <div className="absolute right-0 top-10 z-50 w-56 rounded-2xl border border-border bg-card p-2 shadow-[0_18px_40px_rgba(0,0,0,0.15)]">
                  <div className="border-b border-border px-3 py-2">
                    <p className="truncate text-sm font-semibold text-foreground" title={user?.full_name || undefined}>{user?.full_name || 'User'}</p>
                    <p className="truncate text-xs text-muted-foreground" title={user?.email}>{user?.email}</p>
                    {tenant && (
                      <p className="mt-1 truncate text-xs text-primary" title={tenant.name}>{tenant.name}</p>
                    )}
                  </div>
                  <div className="pt-2">
                    <button
                      type="button"
                      onClick={() => { setProfileOpen(false); navigate('/profile'); }}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-foreground transition hover:bg-muted/50"
                    >
                      <UserIcon className="h-4 w-4" />
                      Profile
                    </button>
                    <button
                      type="button"
                      onClick={() => { setProfileOpen(false); logout(); navigate('/login'); }}
                      className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-foreground transition hover:bg-destructive/10 hover:text-destructive"
                    >
                      <LogOut className="h-4 w-4" />
                      Sign out
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Mobile hamburger */}
            <button
              type="button"
              onClick={() => setMobileMenuOpen(true)}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground lg:hidden"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>
          </div>
        </div>
      </nav>

      {/* ── Mobile bottom-sheet menu ── */}
      {mobileMenuOpen && (
        <>
          <div className="fixed inset-0 z-50 bg-black/30 backdrop-blur-sm lg:hidden" onClick={() => setMobileMenuOpen(false)} />
          <div
            className="fixed inset-x-0 bottom-0 z-50 max-h-[80vh] rounded-t-2xl bg-card p-5 shadow-xl lg:hidden overflow-y-auto"
            style={{ animation: 'slideUpSheet 0.3s ease-out' }}
          >
            <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-muted-foreground/30" />
            <div className="mb-4 flex items-center justify-between">
              <NeuralPrismIcon size={28} />
              <button
                type="button"
                onClick={() => setMobileMenuOpen(false)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="space-y-1">
              {sections.map((section) =>
                section.items.map((item) => {
                  const Icon = item.icon;
                  return (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      onClick={() => setMobileMenuOpen(false)}
                      className={({ isActive }) =>
                        cn(
                          'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition',
                          isActive ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                        )
                      }
                    >
                      <Icon className="h-4 w-4" />
                      {item.label}
                    </NavLink>
                  );
                }),
              )}
            </div>
            <div className="mt-6 border-t border-border pt-4">
              <button
                type="button"
                onClick={() => { setMobileMenuOpen(false); logout(); navigate('/login'); }}
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive"
              >
                <LogOut className="h-4 w-4" />
                Sign Out
              </button>
            </div>
          </div>
          <style>{`
            @keyframes slideUpSheet {
              from { transform: translateY(100%); }
              to { transform: translateY(0); }
            }
          `}</style>
        </>
      )}
    </>
  );
};
