import React from 'react';
import { Bell, Check, ChevronRight, LogOut, Menu, User as UserIcon } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';

import { cn } from '@/lib/utils';
import { useAuth, useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications } from '@/hooks';

interface TopBarProps {
  collapsed: boolean;
  onOpenMobile: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({ collapsed, onOpenMobile }) => {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const location = useLocation();
  const { data: notifications } = useNotifications();
  const markNotificationRead = useMarkNotificationRead();
  const markAllNotificationsRead = useMarkAllNotificationsRead();
  const [notificationsOpen, setNotificationsOpen] = React.useState(false);
  const [profileOpen, setProfileOpen] = React.useState(false);
  const notificationsRef = React.useRef<HTMLDivElement>(null);
  const profileRef = React.useRef<HTMLDivElement>(null);
  const totalCount = notifications?.total_count ?? 0;
  const pageTitle = React.useMemo(() => {
    const map: Record<string, string> = {
      '/dashboard': 'Dashboard',
      '/my-time': 'My Time',
      '/approvals': 'Approvals',
      '/ingestion/inbox': 'Inbox',
      '/mailboxes': 'Mailboxes',
      '/mappings': 'Sender Mappings',
      '/user-management': 'Users',
      '/client-management': 'Clients',
      '/profile': 'Profile',
      '/platform/tenants': 'Tenants',
    };
    return map[location.pathname] ?? 'Workspace';
  }, [location.pathname]);
  const initials = (user?.full_name || 'U')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((chunk) => chunk[0]?.toUpperCase())
    .join('');

  React.useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (notificationsRef.current && !notificationsRef.current.contains(target)) {
        setNotificationsOpen(false);
      }
      if (profileRef.current && !profileRef.current.contains(target)) {
        setProfileOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setNotificationsOpen(false);
        setProfileOpen(false);
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
    if (severity === 'error') return 'bg-red-100 text-red-700';
    if (severity === 'warning') return 'bg-amber-100 text-amber-700';
    if (severity === 'success') return 'bg-emerald-100 text-emerald-700';
    return 'bg-sky-100 text-sky-700';
  };

  const getSeverityLabel = (severity: string) => {
    if (severity === 'error') return 'Alert';
    if (severity === 'warning') return 'Notice';
    if (severity === 'success') return 'Done';
    return 'Info';
  };

  const handleNotificationClick = async (notificationId: string, route: string) => {
    try {
      await markNotificationRead.mutateAsync(notificationId);
    } catch (e) {
      console.error('Failed to mark notification as read:', e);
    } finally {
      setNotificationsOpen(false);
      navigate(route || '/dashboard');
    }
  };

  const handleMarkRead = async (e: React.MouseEvent, notificationId: string) => {
    e.stopPropagation();
    try {
      await markNotificationRead.mutateAsync(notificationId);
    } catch (e) {
      console.error('Failed to mark notification as read:', e);
    }
  };

  const handleProfileNavigate = (path: string) => {
    setProfileOpen(false);
    navigate(path);
  };

  const handleLogout = () => {
    setProfileOpen(false);
    logout();
    navigate('/login');
  };

  return (
    <header className={cn('sticky top-0 z-30 border-b border-border bg-card')}>
      <div className="mx-auto flex h-[52px] max-w-[1800px] items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            onClick={onOpenMobile}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-muted text-muted-foreground transition hover:text-foreground lg:hidden"
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="min-w-0">
            <p className="truncate text-[15px] font-semibold text-foreground">{pageTitle}</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div ref={notificationsRef} className="relative">
            <button
              type="button"
              onClick={() => {
                setNotificationsOpen((open) => !open);
                setProfileOpen(false);
              }}
              className="relative inline-flex h-9 w-9 items-center justify-center rounded-md bg-muted text-muted-foreground transition hover:text-foreground"
              aria-label="Open notifications"
              aria-expanded={notificationsOpen}
            >
              <Bell className="h-4 w-4" />
              {totalCount > 0 && (
                <span className="absolute -right-1 -top-1 inline-flex min-h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-[11px] font-semibold text-white">
                  {totalCount > 99 ? '99+' : totalCount}
                </span>
              )}
            </button>
            {notificationsOpen && (
              <div className="absolute right-0 top-11 z-40 w-[360px] rounded-2xl border border-border bg-card p-2 shadow-[0_18px_40px_rgba(15,23,42,0.12)]">
                <div className="flex items-center justify-between px-3 py-2">
                  <div>
                    <p className="text-sm font-semibold text-foreground">Notifications</p>
                    <p className="text-xs text-muted-foreground">{totalCount} unread items</p>
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
                    <div className="px-3 py-8 text-center text-sm text-muted-foreground">No notifications right now.</div>
                  ) : (
                    (notifications?.items ?? []).map((item) => (
                      <div key={item.id} className="group relative flex items-start gap-3 rounded-xl px-3 py-3 transition hover:bg-muted/50">
                        <button
                          type="button"
                          onClick={() => void handleNotificationClick(item.id, item.route)}
                          className="flex min-w-0 flex-1 items-start gap-3 text-left"
                          aria-label={`Go to ${item.title}`}
                        >
                          <span className={cn('mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase', getSeverityClasses(item.severity))}>
                            {getSeverityLabel(item.severity)}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-start gap-2">
                              <p className="truncate text-sm font-medium text-foreground">{item.title}</p>
                              {!item.is_read && <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-primary" />}
                            </div>
                            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{item.message}</p>
                          </div>
                          <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                        </button>
                        {!item.is_read && (
                          <button
                            type="button"
                            onClick={(e) => void handleMarkRead(e, item.id)}
                            className="absolute right-2 top-2 hidden h-5 w-5 items-center justify-center rounded-full bg-muted text-muted-foreground transition hover:bg-primary hover:text-white group-hover:flex"
                            aria-label="Mark as read"
                            title="Mark as read"
                          >
                            <Check className="h-3 w-3" />
                          </button>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
          <div ref={profileRef} className="relative">
            <button
              type="button"
              onClick={() => {
                setProfileOpen((open) => !open);
                setNotificationsOpen(false);
              }}
              className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-[var(--accent-light)] text-[11px] font-semibold text-primary transition hover:opacity-85"
              aria-label="Open profile menu"
              aria-expanded={profileOpen}
            >
              {initials || 'U'}
            </button>
            {profileOpen && (
              <div className="absolute right-0 top-10 z-40 w-56 rounded-2xl border border-border bg-card p-2 shadow-[0_18px_40px_rgba(15,23,42,0.12)]">
                <div className="border-b border-border px-3 py-2">
                  <p className="truncate text-sm font-semibold text-foreground">{user?.full_name || 'User'}</p>
                  <p className="truncate text-xs text-muted-foreground">{user?.email || ''}</p>
                </div>
                <div className="pt-2">
                  <button
                    type="button"
                    onClick={() => handleProfileNavigate('/profile')}
                    className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-foreground transition hover:bg-muted/50"
                  >
                    <UserIcon className="h-4 w-4" />
                    Profile
                  </button>
                  <button
                    type="button"
                    onClick={handleLogout}
                    className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-foreground transition hover:bg-muted/50"
                  >
                    <LogOut className="h-4 w-4" />
                    Sign out
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};
