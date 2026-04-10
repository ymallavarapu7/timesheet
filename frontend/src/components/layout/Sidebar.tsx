import React from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { ChevronLeft, LogOut } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { buildNavigation } from '@/components/layout/navigation';
import { cn } from '@/lib/utils';
import { useAuth, useCanReview, useIngestionEnabled, useIsPlatformAdmin } from '@/hooks';

interface SidebarProps {
  isMobileOpen: boolean;
  onCloseMobile: () => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  isMobileOpen,
  onCloseMobile,
  collapsed,
  onToggleCollapsed,
}) => {
  const { user, tenant, logout } = useAuth();
  const navigate = useNavigate();
  const ingestionEnabled = useIngestionEnabled();
  const canReview = useCanReview();
  const isPlatformAdmin = useIsPlatformAdmin();
  const sections = buildNavigation(user, ingestionEnabled);

  const sidebar = (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-50 flex w-[220px] flex-col border-r border-border bg-card px-3 pb-4 pt-5 transition-transform duration-300',
        collapsed && 'xl:w-[88px]',
        isMobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
      )}
    >
      <div className="mb-6 flex items-start justify-between gap-3">
        <Link to="/dashboard" className="min-w-0" onClick={onCloseMobile}>
          <p className={cn('text-base font-semibold text-foreground', collapsed && 'xl:hidden')}>{isPlatformAdmin ? 'Platform Administration' : tenant?.name || 'Workspace'}</p>
          <p className={cn('mt-1 text-xs font-medium text-primary/70', collapsed && 'xl:hidden')}>TimesheetIQ</p>
          <div className={cn('mt-3 flex flex-wrap gap-2', collapsed && 'xl:hidden')}>
            {ingestionEnabled && <Badge tone="warning">Ingestion</Badge>}
            {canReview && <Badge tone="info">Reviewer</Badge>}
            {isPlatformAdmin && <Badge tone="outline">Platform</Badge>}
          </div>
        </Link>
        <button
          type="button"
          onClick={onToggleCollapsed}
          className="hidden h-9 w-9 items-center justify-center rounded-md border border-transparent bg-muted text-muted-foreground transition hover:bg-slate-200 hover:text-foreground xl:inline-flex"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <ChevronLeft className={cn('h-4 w-4 transition', collapsed && 'rotate-180')} />
        </button>
      </div>

      {!collapsed && (
        <div className="mb-6 rounded-lg bg-muted px-3 py-3 xl:block">
          <p className="text-sm font-semibold text-foreground">{user?.full_name}</p>
          <p className="mt-1 text-xs uppercase tracking-[0.12em] text-muted-foreground">{user?.title || user?.role}</p>
          <p className="mt-3 text-xs text-muted-foreground">{user?.email}</p>
        </div>
      )}

      <div className="flex-1 space-y-6 overflow-y-auto pr-1">
        {sections.map((section) => (
          <div key={section.title}>
            {!collapsed && <p className="mb-2 border-l-2 border-primary/30 px-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{section.title}</p>}
            <div className="space-y-1">
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={onCloseMobile}
                  className={({ isActive }) =>
                    cn(
                      'group flex items-center gap-3 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition',
                      'hover:bg-muted hover:text-foreground',
                      isActive && 'rounded-r-md rounded-l-none border-l-2 border-primary bg-[var(--accent-light)] text-primary',
                      collapsed && 'justify-center xl:px-0',
                    )
                  }
                >
                  <item.icon className="h-4 w-4 shrink-0" />
                  {!collapsed && <span>{item.label}</span>}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={() => {
          logout();
          onCloseMobile();
          navigate('/login', { replace: true });
        }}
        className={cn(
          'mt-4 flex items-center gap-3 rounded-md border border-transparent bg-muted px-3 py-2 text-sm font-medium text-muted-foreground transition hover:bg-red-50 hover:text-red-700',
          collapsed && 'justify-center xl:px-0',
        )}
      >
        <LogOut className="h-4 w-4 shrink-0" />
        {!collapsed && <span>Sign Out</span>}
      </button>
    </aside>
  );

  return (
    <>
      <div className={cn('fixed inset-0 z-40 bg-black/20 lg:hidden', isMobileOpen ? 'block' : 'hidden')} onClick={onCloseMobile} />
      {sidebar}
    </>
  );
};

