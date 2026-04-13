import React, { useState } from 'react';
import { Link, NavLink, useNavigate, useLocation } from 'react-router-dom';
import { ChevronDown, ChevronLeft, LogOut } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { buildNavigation } from '@/components/layout/navigation';
import { AcufyLogo, NeuralPrismIcon } from '@/components/layout/AcufyLogo';
import { cn } from '@/lib/utils';
import { useAuth, useCanReview, useIngestionEnabled, useIsPlatformAdmin } from '@/hooks';
import type { LucideIcon } from 'lucide-react';

const SectionIcon: React.FC<{ icon: LucideIcon }> = ({ icon: Icon }) => (
  <Icon className="h-4 w-4 shrink-0" />
);

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
  const location = useLocation();
  const ingestionEnabled = useIngestionEnabled();
  const canReview = useCanReview();
  const isPlatformAdmin = useIsPlatformAdmin();
  const sections = buildNavigation(user, ingestionEnabled);

  // Track which dropdown sections are open
  const [openSections, setOpenSections] = useState<Record<string, boolean>>(() => {
    // Auto-open the section that contains the current route
    const initial: Record<string, boolean> = {};
    for (const section of sections) {
      const isActive = section.items.some(
        (item) =>
          location.pathname === item.to ||
          item.match?.some((m) => location.pathname.startsWith(m)),
      );
      if (isActive) initial[section.title] = true;
    }
    return initial;
  });

  const toggleSection = (title: string) => {
    setOpenSections((prev) => ({ ...prev, [title]: !prev[title] }));
  };

  const isItemActive = (item: { to: string; match?: string[] }) =>
    location.pathname === item.to ||
    item.match?.some((m) => location.pathname.startsWith(m)) ||
    false;

  const sidebar = (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-50 flex flex-col border-r transition-all duration-300',
        'bg-card/95 backdrop-blur-xl',
        collapsed ? 'xl:w-[72px] w-[220px]' : 'w-[240px]',
        isMobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
      )}
      style={{ borderColor: 'var(--glass-border)' }}
    >
      {/* ── Logo area ── */}
      <div className="flex items-center justify-between px-4 py-4">
        <Link to="/dashboard" className="min-w-0" onClick={onCloseMobile}>
          {collapsed ? (
            <span className="hidden xl:block"><NeuralPrismIcon size={32} /></span>
          ) : null}
          <span className={cn(collapsed && 'xl:hidden')}>
            <AcufyLogo variant="full" />
          </span>
        </Link>
        <button
          type="button"
          onClick={onToggleCollapsed}
          className="hidden h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground xl:inline-flex"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <ChevronLeft className={cn('h-4 w-4 transition', collapsed && 'rotate-180')} />
        </button>
      </div>

      {/* ── Workspace / user info ── */}
      {!collapsed && (
        <div className="mx-3 mb-3 rounded-lg border border-border/50 bg-muted/50 px-3 py-2.5">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-primary">
            {isPlatformAdmin ? 'Platform Admin' : tenant?.name || 'Workspace'}
          </p>
          <p className="mt-1 truncate text-[11px] text-muted-foreground">{user?.full_name}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {ingestionEnabled && <Badge tone="warning">Ingestion</Badge>}
            {canReview && <Badge tone="info">Reviewer</Badge>}
            {isPlatformAdmin && <Badge tone="outline">Platform</Badge>}
          </div>
        </div>
      )}

      {/* ── Top gradient line ── */}
      <div className="mx-4 h-[2px] rounded-full" style={{ background: 'linear-gradient(90deg, #0EA5E9, #06B6D4, #14B8A6, #2DD4BF)' }} />

      {/* ── Navigation sections with dropdowns ── */}
      <div className="mt-3 flex-1 space-y-1 overflow-y-auto px-3 pb-2">
        {sections.map((section) => {
          const isOpen = openSections[section.title] ?? false;
          const hasActiveChild = section.items.some((item) => isItemActive(item));

          // Single-item sections don't need a dropdown
          if (section.items.length === 1) {
            const item = section.items[0];
            return (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={onCloseMobile}
                className={() =>
                  cn(
                    'group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition',
                    'hover:bg-muted/80 hover:text-foreground',
                    isItemActive(item) && 'bg-primary/10 text-primary',
                    collapsed && 'justify-center xl:px-0',
                  )
                }
              >
                <item.icon className="h-4 w-4 shrink-0" />
                {!collapsed && <span>{item.label}</span>}
              </NavLink>
            );
          }

          return (
            <div key={section.title}>
              {/* Section header / dropdown trigger */}
              <button
                type="button"
                onClick={() => !collapsed && toggleSection(section.title)}
                className={cn(
                  'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold transition',
                  hasActiveChild
                    ? 'text-primary'
                    : 'text-muted-foreground hover:bg-muted/80 hover:text-foreground',
                  collapsed && 'justify-center xl:px-0',
                )}
              >
                {/* Use the first item's icon as section icon when collapsed */}
                {collapsed && <SectionIcon icon={section.items[0].icon} />}
                {!collapsed && (
                  <>
                    <span className="flex-1 text-left text-xs uppercase tracking-[0.08em]">{section.title}</span>
                    <ChevronDown
                      className={cn(
                        'h-3.5 w-3.5 text-muted-foreground transition-transform duration-200',
                        isOpen && 'rotate-180',
                      )}
                    />
                  </>
                )}
              </button>

              {/* Dropdown items */}
              {!collapsed && (
                <div
                  className={cn(
                    'overflow-hidden transition-all duration-200',
                    isOpen ? 'max-h-[500px] opacity-100' : 'max-h-0 opacity-0',
                  )}
                >
                  <div className="ml-2 space-y-0.5 border-l-2 border-primary/15 pl-2 pt-1">
                    {section.items.map((item) => (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        onClick={onCloseMobile}
                        className={() =>
                          cn(
                            'group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium text-muted-foreground transition',
                            'hover:bg-muted/80 hover:text-foreground',
                            isItemActive(item) && 'bg-primary/10 text-primary font-semibold',
                          )
                        }
                      >
                        <item.icon className="h-3.5 w-3.5 shrink-0" />
                        <span>{item.label}</span>
                      </NavLink>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Sign out ── */}
      <div className="border-t border-border/50 px-3 py-3">
        <button
          type="button"
          onClick={() => {
            logout();
            onCloseMobile();
            navigate('/login', { replace: true });
          }}
          className={cn(
            'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition',
            'hover:bg-destructive/10 hover:text-destructive',
            collapsed && 'justify-center xl:px-0',
          )}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {!collapsed && <span>Sign Out</span>}
        </button>
      </div>
    </aside>
  );

  return (
    <>
      <div
        className={cn(
          'fixed inset-0 z-40 bg-black/30 backdrop-blur-sm lg:hidden',
          isMobileOpen ? 'block' : 'hidden',
        )}
        onClick={onCloseMobile}
      />
      {sidebar}
    </>
  );
};
