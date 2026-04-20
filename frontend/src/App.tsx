import React from 'react';
import { BrowserRouter as Router, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';

import { AuthProvider } from '@/contexts/AuthContext';
import { ThemeProvider } from '@/contexts/ThemeContext';
import { AppLayout, Loading } from '@/components';
import { useAuth, useCanReview, useIngestionEnabled } from '@/hooks';
import {
  AdminPage,
  AdminSettingsPage,
  ApprovalsPage,
  AuditTrailPage,
  CalendarPage,
  ClientManagementPage,
  DashboardPage,
  InboxPage,
  LoginPage,
  MailboxesPage,
  MyTimePage,
  PlatformAdminPage,
  PlatformSettingsPage,
  ProfilePage,
  ReviewPanelPage,
  TimeOffPage,
  VerifyAccountPage,
} from '@/pages';

import { queryClient } from '@/lib/queryClient';

const getPostLoginRoute = (role?: string) => (role === 'PLATFORM_ADMIN' ? '/platform/tenants' : '/dashboard');

const HomeRedirect: React.FC = () => {
  const { user } = useAuth();
  return <Navigate to={getPostLoginRoute(user?.role)} replace />;
};

const ProtectedRoute: React.FC = () => {
  const { user, isLoading, accessToken } = useAuth();

  console.log('[ProtectedRoute]', { hasUser: !!user, isLoading, hasToken: !!accessToken, role: user?.role });

  if (isLoading) {
    return <Loading message="Restoring your workspace..." />;
  }

  if (!user) {
    console.warn('[ProtectedRoute] No user, redirecting to login. Token in localStorage:', !!localStorage.getItem('accessToken'));
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
};

const AnonymousOnlyRoute: React.FC = () => {
  const { user } = useAuth();

  if (user) {
    return <Navigate to={getPostLoginRoute(user.role)} replace />;
  }

  return <LoginPage />;
};

const PlatformAdminGuard: React.FC = () => {
  const { user } = useAuth();
  return user?.role === 'PLATFORM_ADMIN' ? <Outlet /> : <Navigate to="/dashboard" replace />;
};

const ManagerGuard: React.FC = () => {
  const { user } = useAuth();
  return user && ['MANAGER', 'SENIOR_MANAGER', 'CEO', 'ADMIN'].includes(user.role)
    ? <Outlet />
    : <Navigate to="/dashboard" replace />;
};

const IngestionEnabledGuard: React.FC = () => {
  return useIngestionEnabled() ? <Outlet /> : <Navigate to="/dashboard" replace />;
};

const ReviewGuard: React.FC = () => {
  return useCanReview() ? <Outlet /> : <Navigate to="/dashboard" replace />;
};

const TenantAdminGuard: React.FC = () => {
  const { user } = useAuth();
  return user?.role === 'ADMIN' ? <Outlet /> : <Navigate to="/dashboard" replace />;
};

const AdminOrManagerGuard: React.FC = () => {
  const { user } = useAuth();
  return user && ['ADMIN', 'MANAGER', 'SENIOR_MANAGER', 'CEO'].includes(user.role)
    ? <Outlet />
    : <Navigate to="/dashboard" replace />;
};

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<AnonymousOnlyRoute />} />
      <Route path="/verify-account" element={<VerifyAccountPage />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<HomeRedirect />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/my-time" element={<MyTimePage />} />
          <Route path="/time-off" element={<TimeOffPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route element={<AdminOrManagerGuard />}>
            <Route path="/user-management" element={<AdminPage />} />
          </Route>
          <Route element={<TenantAdminGuard />}>
            <Route path="/client-management" element={<ClientManagementPage />} />
            <Route path="/audit-trail" element={<AuditTrailPage />} />
            <Route path="/settings" element={<AdminSettingsPage />} />
          </Route>

          <Route element={<ManagerGuard />}>
            <Route path="/approvals" element={<ApprovalsPage />} />
          </Route>

          <Route element={<PlatformAdminGuard />}>
            <Route path="/platform/tenants" element={<PlatformAdminPage />} />
            <Route path="/platform/settings" element={<PlatformSettingsPage />} />
            <Route path="/platform-admin" element={<Navigate to="/platform/tenants" replace />} />
          </Route>

          <Route element={<IngestionEnabledGuard />}>
            <Route element={<TenantAdminGuard />}>
              <Route path="/mailboxes" element={<MailboxesPage />} />
            </Route>

            <Route element={<ReviewGuard />}>
              <Route path="/ingestion/inbox" element={<InboxPage />} />
              <Route path="/ingestion/email/:emailId" element={<ReviewPanelPage />} />
              <Route path="/ingestion/review/:timesheetId" element={<ReviewPanelPage />} />
            </Route>
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<HomeRedirect />} />
    </Routes>
  );
}

export function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <Router basename={import.meta.env.BASE_URL}>
          <AuthProvider>
            <AppRoutes />
          </AuthProvider>
        </Router>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export default App;
