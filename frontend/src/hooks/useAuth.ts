import { useContext } from 'react';

import { AuthContext } from '@/contexts/AuthContext';

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

export const useIsAuthenticated = () => {
  const { user } = useAuth();
  return Boolean(user);
};

export const useUserRole = () => {
  const { user } = useAuth();
  return user?.role;
};

export const useHasRole = (requiredRoles: string[]) => {
  const role = useUserRole();
  return role ? requiredRoles.includes(role) : false;
};

export const useIsAdmin = () => useHasRole(['ADMIN']);
export const useIsPlatformAdmin = () => useHasRole(['PLATFORM_ADMIN']);
export const useIsCEO = () => useHasRole(['CEO']);
export const useIsSeniorManager = () => useHasRole(['SENIOR_MANAGER']);
export const useIsManager = () => useHasRole(['MANAGER', 'SENIOR_MANAGER', 'CEO']);
export const useIsEmployee = () => useHasRole(['EMPLOYEE', 'MANAGER', 'SENIOR_MANAGER', 'CEO', 'ADMIN']);

export const useCanReview = () => {
  const { user } = useAuth();
  return Boolean(user && (user.role === 'ADMIN' || user.can_review));
};

export const useIsReviewer = () => useCanReview();

export const useIngestionEnabled = () => {
  const { tenant } = useAuth();
  return Boolean(tenant?.ingestion_enabled);
};
