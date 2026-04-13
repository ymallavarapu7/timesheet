import React from 'react';
import { Outlet } from 'react-router-dom';

import { TopNavBar } from '@/components/layout/TopNavBar';

export const AppLayout: React.FC = () => {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <TopNavBar />
      <main className="mx-auto w-full max-w-[1800px] flex-1 px-5 py-6 sm:px-6 lg:px-8">
        <Outlet />
      </main>
      <footer className="border-t border-border/50 py-5 text-center">
        <p className="text-xs text-muted-foreground">&copy; 2026 Acufy AI. All rights reserved.</p>
      </footer>
    </div>
  );
};
