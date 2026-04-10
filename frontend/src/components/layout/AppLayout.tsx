import React from 'react';
import { Outlet } from 'react-router-dom';

import { Sidebar } from '@/components/layout/Sidebar';
import { TopBar } from '@/components/layout/TopBar';
import { cn } from '@/lib/utils';

export const AppLayout: React.FC = () => {
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [collapsed, setCollapsed] = React.useState(false);

  return (
    <div className="min-h-screen bg-background">
      <Sidebar
        isMobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed((value) => !value)}
      />
      <div className={cn('min-h-screen transition-[padding] duration-300', collapsed ? 'xl:pl-[88px]' : 'xl:pl-[220px]')}>
        <TopBar collapsed={collapsed} onOpenMobile={() => setMobileOpen(true)} />
        <main className="mx-auto max-w-[1800px] px-7 py-7 sm:px-7 lg:px-7">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
