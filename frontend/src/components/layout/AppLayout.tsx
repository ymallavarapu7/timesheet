import React from 'react';
import { Outlet, useNavigate } from 'react-router-dom';

import { PortalPickerModal } from '@/components/PortalPickerModal';
import { TopNavBar } from '@/components/layout/TopNavBar';
import { useAuth } from '@/hooks';
import type { UserRole } from '@/types';

const getPostPickRoute = (role: UserRole): string =>
  role === 'PLATFORM_ADMIN' ? '/platform/tenants' : '/dashboard';

export const AppLayout: React.FC = () => {
  const { user, needsRolePick, switchRole, dismissRolePick } = useAuth();
  const navigate = useNavigate();
  const [pickPending, setPickPending] = React.useState(false);
  const [pickError, setPickError] = React.useState<string | null>(null);

  const handlePick = async (role: UserRole) => {
    if (!user) return;
    setPickPending(true);
    setPickError(null);
    try {
      if (user.role === role) {
        // User accepted the active role from login; just dismiss.
        dismissRolePick();
        navigate(getPostPickRoute(role));
        return;
      }
      const next = await switchRole(role);
      navigate(getPostPickRoute(next.role));
    } catch (err) {
      setPickError(err instanceof Error ? err.message : 'Could not switch role');
    } finally {
      setPickPending(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <TopNavBar />
      <main className="mx-auto w-full max-w-[1800px] flex-1 px-5 py-6 sm:px-6 lg:px-8">
        <Outlet />
      </main>
      <footer className="border-t border-border/50 py-5 text-center">
        <p className="text-xs text-muted-foreground">&copy; 2026 Acufy AI. All rights reserved.</p>
      </footer>

      {/* Multi-role users see this immediately after a fresh login. The
          modal lives at the layout level (not LoginPage) so it survives
          the AnonymousOnlyRoute → ProtectedRoute redirect that fires as
          soon as the auth state flips to authenticated. */}
      <PortalPickerModal
        isOpen={Boolean(user) && needsRolePick}
        roles={user?.roles ?? []}
        currentRole={user?.role}
        onPick={handlePick}
        pending={pickPending}
      />
      {pickError && needsRolePick && (
        <div className="fixed left-1/2 top-4 z-[70] -translate-x-1/2 rounded-lg bg-destructive/90 px-4 py-2 text-sm text-white shadow-lg">
          {pickError}
        </div>
      )}
    </div>
  );
};
