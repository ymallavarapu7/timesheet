import React, { createContext, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import axios from 'axios';

import { authAPI, ingestionAPI, mailboxesAPI, tenantsAPI } from '@/api/endpoints';
import { queryClient } from '@/lib/queryClient';
import type { Tenant, User, UserRole } from '@/types';

interface AuthContextType {
  user: User | null;
  tenant: Tenant | null;
  accessToken: string | null;
  isLoading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<User>;
  loginWithRoleHandoff: (handoffToken: string) => Promise<User>;
  switchRole: (role: UserRole) => Promise<User>;
  /** True when the just-authenticated user has more than one role and
   *  hasn't yet picked one for this session. The AppLayout reads this
   *  to render the portal-picker modal blocking-style. */
  needsRolePick: boolean;
  /** Dismiss the picker without switching (the user accepts the
   *  active role from login). */
  dismissRolePick: () => void;
  logout: () => void;
  refreshUser: () => Promise<void>;
  refreshTenant: (nextUser?: User | null) => Promise<void>;
}

const USER_STORAGE_KEY = 'user';
const TENANT_STORAGE_KEY = 'tenant';
const TOKEN_STORAGE_KEY = 'accessToken';
const REFRESH_TOKEN_STORAGE_KEY = 'refreshToken';

// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext<AuthContextType | undefined>(undefined);

const extractErrorMessage = (error: unknown): string => {
  if (axios.isAxiosError(error)) {
    if (typeof error.response?.data?.detail === 'string') {
      return error.response.data.detail;
    }
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return 'Authentication failed';
};

const createTenantFallback = (user: User): Tenant | null => {
  if (!user.tenant_id) return null;
  // Minimal placeholder used only when /tenants/mine fails. Do NOT read from
  // sessionStorage — stale cached names (e.g. "Timesheet Application" from an
  // old seed) would display even after the DB has been updated.
  return {
    id: user.tenant_id,
    name: 'Workspace',
    slug: `tenant-${user.tenant_id}`,
    status: 'active',
    ingestion_enabled: false,
    created_at: '',
    updated_at: '',
  };
};

const inferIngestionEnabled = async (user: User): Promise<boolean> => {
  try {
    if (user.role === 'ADMIN') {
      await mailboxesAPI.list();
      return true;
    }
    if (user.can_review) {
      await ingestionAPI.listTimesheets({ limit: 1 });
      return true;
    }
  } catch (error) {
    if (axios.isAxiosError(error) && typeof error.response?.data?.detail === 'string') {
      return !error.response.data.detail.toLowerCase().includes('not enabled');
    }
  }

  return false;
};

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [needsRolePick, setNeedsRolePick] = useState(false);
  const sessionVersionRef = useRef(0);

  const dismissRolePick = useCallback(() => setNeedsRolePick(false), []);

  // Flip needsRolePick based on the just-authenticated user. We trip
  // it true only when login establishes a new session (vs a passive
  // /auth/me refresh or a token-exchange flow that already targets a
  // specific role). Callers pass `arrivedFresh=true` in those cases.
  const reconcileRolePick = useCallback((nextUser: User | null, arrivedFresh: boolean) => {
    if (!nextUser) {
      setNeedsRolePick(false);
      return;
    }
    const roles = nextUser.roles ?? [];
    if (arrivedFresh && roles.length > 1) {
      setNeedsRolePick(true);
    } else {
      setNeedsRolePick(false);
    }
  }, []);

  const persistAuthState = useCallback((_nextUser: User | null, _nextTenant: Tenant | null, nextToken: string | null) => {
    // We cache the token (axios interceptor reads it synchronously) but NOT the
    // user/tenant objects — fetching /auth/me and /tenants/mine fresh on every
    // page load avoids stale-identity bugs when users get reassigned, renamed,
    // or moved between tenants.
    if (nextToken) sessionStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
    else sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    sessionStorage.removeItem(USER_STORAGE_KEY);
    sessionStorage.removeItem(TENANT_STORAGE_KEY);
  }, []);

  const logout = useCallback(() => {
    sessionVersionRef.current += 1;
    // Revoke the refresh token server-side (best-effort, don't block logout)
    const savedRefresh = sessionStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
    if (savedRefresh) {
      authAPI.logout(savedRefresh).catch(() => {});
    }
    setUser(null);
    setTenant(null);
    setAccessToken(null);
    setError(null);
    sessionStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
    persistAuthState(null, null, null);
    queryClient.clear();
  }, [persistAuthState]);

  const refreshTenant = useCallback(async (nextUser?: User | null) => {
    const userToUse = nextUser ?? user;
    if (!userToUse?.tenant_id) {
      setTenant(null);
      return;
    }

    try {
      // Use /tenants/mine for regular users (works for all roles),
      // fall back to /tenants/{id} for PLATFORM_ADMIN
      const response = userToUse.role === 'PLATFORM_ADMIN'
        ? await tenantsAPI.get(userToUse.tenant_id)
        : await tenantsAPI.mine();
      setTenant(response.data);
      return;
    } catch {
      const fallback = createTenantFallback(userToUse);
      if (fallback && (userToUse.role === 'ADMIN' || userToUse.can_review)) {
        try {
          fallback.ingestion_enabled = await inferIngestionEnabled(userToUse);
        } catch {
          fallback.ingestion_enabled = false;
        }
      }
      setTenant(fallback);
    }
  }, [user]);

  const refreshUser = useCallback(async () => {
    // accessToken state may not yet be in scope on the very first call right
    // after a session restore, so also accept the sessionStorage token.
    if (!accessToken && !sessionStorage.getItem(TOKEN_STORAGE_KEY)) return;
    const refreshSessionVersion = sessionVersionRef.current;

    try {
      const response = await authAPI.me();
      // Ignore stale responses if the user has logged out/logged in since request started.
      if (refreshSessionVersion !== sessionVersionRef.current || !sessionStorage.getItem(TOKEN_STORAGE_KEY)) {
        return;
      }
      setUser(response.data);
      await refreshTenant(response.data);
    } catch (err) {
      if (refreshSessionVersion === sessionVersionRef.current) {
        // Only logout if the server explicitly rejected the token (401).
        // Network errors, 500s, and 403s should not force a logout.
        const is401 = axios.isAxiosError(err) && err.response?.status === 401;
        if (is401) {
          logout();
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  const login = useCallback(async (email: string, password: string) => {
    sessionVersionRef.current += 1;
    setIsLoading(true);
    setError(null);

    try {
      const response = await authAPI.login({ email: email.trim().toLowerCase(), password });
      const { access_token, refresh_token: refreshToken, user: nextUser, previous_last_login_at } = response.data;
      setUser(nextUser);
      setAccessToken(access_token);
      if (refreshToken) sessionStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, refreshToken);
      // Stash for the dashboard "N new since last login" chip.
      if (previous_last_login_at) {
        sessionStorage.setItem('previous_last_login_at', previous_last_login_at);
      } else {
        sessionStorage.removeItem('previous_last_login_at');
      }
      persistAuthState(nextUser, null, access_token);

      let nextTenant: Tenant | null = null;
      if (nextUser.tenant_id) {
        try {
          const tenantResponse = nextUser.role === 'PLATFORM_ADMIN'
            ? await tenantsAPI.get(nextUser.tenant_id)
            : await tenantsAPI.mine();
          nextTenant = tenantResponse.data;
        } catch {
          nextTenant = createTenantFallback(nextUser);
          if (nextTenant && (nextUser.role === 'ADMIN' || nextUser.can_review)) {
            nextTenant.ingestion_enabled = await inferIngestionEnabled(nextUser);
          }
        }
      }

      setTenant(nextTenant);
      persistAuthState(nextUser, nextTenant, access_token);
      // Fresh login: if multi-role, the layout will show the picker
      // before letting the user interact with the dashboard.
      reconcileRolePick(nextUser, true);
      return nextUser;
    } catch (err: unknown) {
      const message = extractErrorMessage(err);
      setError(message);
      throw new Error(message);
    } finally {
      setIsLoading(false);
    }
  }, [persistAuthState, reconcileRolePick]);

  // Multi-role new-tab handoff: exchange ?role-handoff=<token> for an
  // independent session in this tab's sessionStorage.
  const loginWithRoleHandoff = useCallback(async (handoffToken: string) => {
    sessionVersionRef.current += 1;
    setIsLoading(true);
    setError(null);

    try {
      const response = await authAPI.roleHandoffExchange(handoffToken);
      const { access_token, refresh_token: refreshToken, user: nextUser } = response.data;
      setUser(nextUser);
      setAccessToken(access_token);
      if (refreshToken) sessionStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, refreshToken);
      persistAuthState(nextUser, null, access_token);

      let nextTenant: Tenant | null = null;
      if (nextUser.tenant_id) {
        try {
          const tenantResponse = nextUser.role === 'PLATFORM_ADMIN'
            ? await tenantsAPI.get(nextUser.tenant_id)
            : await tenantsAPI.mine();
          nextTenant = tenantResponse.data;
        } catch {
          nextTenant = createTenantFallback(nextUser);
          if (nextTenant && (nextUser.role === 'ADMIN' || nextUser.can_review)) {
            nextTenant.ingestion_enabled = await inferIngestionEnabled(nextUser);
          }
        }
      }

      setTenant(nextTenant);
      persistAuthState(nextUser, nextTenant, access_token);
      // Role-handoff lands the new tab already in the chosen role; the
      // picker should not appear here.
      reconcileRolePick(nextUser, false);
      return nextUser;
    } catch (err: unknown) {
      const message = extractErrorMessage(err);
      setError(message);
      throw new Error(message);
    } finally {
      setIsLoading(false);
    }
  }, [persistAuthState, reconcileRolePick]);

  // Multi-role: flip the active role within the current session. Calls
  // POST /auth/switch-role, swaps the new tokens into sessionStorage,
  // and updates user/tenant state. Caller is expected to navigate to
  // the appropriate landing page after this resolves.
  const switchRole = useCallback(async (role: UserRole) => {
    sessionVersionRef.current += 1;
    setIsLoading(true);
    setError(null);

    try {
      const response = await authAPI.switchRole(role);
      const { access_token, refresh_token: refreshToken, user: nextUser } = response.data;
      setUser(nextUser);
      setAccessToken(access_token);
      if (refreshToken) sessionStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, refreshToken);
      persistAuthState(nextUser, null, access_token);

      // Tenant doesn't change on a role switch (same user, same
      // tenant_id), but we re-fetch in case ingestion_enabled or
      // tenant settings have changed since login.
      let nextTenant: Tenant | null = tenant;
      if (nextUser.tenant_id) {
        try {
          const tenantResponse = nextUser.role === 'PLATFORM_ADMIN'
            ? await tenantsAPI.get(nextUser.tenant_id)
            : await tenantsAPI.mine();
          nextTenant = tenantResponse.data;
        } catch {
          // Keep the current tenant if the refresh fails; we still have
          // a valid session and the rest of the app stays usable.
        }
      }
      setTenant(nextTenant);
      persistAuthState(nextUser, nextTenant, access_token);

      // Cached query data tied to the previous role (e.g., manager
      // approval queues for an admin who never could see them) is
      // stale. Drop it so the next render re-fetches from scratch.
      queryClient.clear();

      // The user has actively chosen a role; the picker should not
      // come back during this session.
      setNeedsRolePick(false);

      return nextUser;
    } catch (err: unknown) {
      const message = extractErrorMessage(err);
      setError(message);
      throw new Error(message);
    } finally {
      setIsLoading(false);
    }
  }, [persistAuthState, tenant]);

  // Restore session from localStorage on mount. Use a ref to call the
  // latest refreshUser without adding it to the dependency array (which
  // would cause infinite re-renders as refreshUser is recreated on every
  // state change).
  const refreshUserRef = useRef(refreshUser);
  refreshUserRef.current = refreshUser;

  useEffect(() => {
    const savedToken = sessionStorage.getItem(TOKEN_STORAGE_KEY);
    const savedRefreshToken = sessionStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
    // Clear any legacy user/tenant cache from earlier versions so it can't leak
    // into the UI on first paint.
    sessionStorage.removeItem(USER_STORAGE_KEY);
    sessionStorage.removeItem(TENANT_STORAGE_KEY);

    if (!savedToken && !savedRefreshToken) {
      setIsLoading(false);
      return;
    }

    if (savedToken) {
      // Set the token immediately so axios/` /auth/me` can fire with it, but
      // keep user/tenant null until we get fresh data back from the server.
      // Nothing flashes on screen because ProtectedRoute shows a spinner while
      // isLoading is true.
      setAccessToken(savedToken);
      void refreshUserRef.current().finally(() => setIsLoading(false));
      return;
    }

    // No access token but have refresh token — attempt silent refresh
    if (savedRefreshToken) {
      const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
      axios.post(`${apiBase}/auth/refresh`, {
        refresh_token: savedRefreshToken,
      }).then((res) => {
        const { access_token, refresh_token: newRefresh } = res.data;
        sessionStorage.setItem(TOKEN_STORAGE_KEY, access_token);
        if (newRefresh) sessionStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, newRefresh);
        setAccessToken(access_token);
        return axios.get(`${apiBase}/auth/me`, {
          headers: { Authorization: `Bearer ${access_token}` },
        });
      }).then((res) => {
        setUser(res.data);
        void refreshUserRef.current();
      }).catch(() => {
        sessionStorage.removeItem(TOKEN_STORAGE_KEY);
        sessionStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
      }).finally(() => {
        setIsLoading(false);
      });
      return;
    }

    setIsLoading(false);
  }, []);

  const value = useMemo<AuthContextType>(
    () => ({
      user,
      tenant,
      accessToken,
      isLoading,
      error,
      login,
      loginWithRoleHandoff,
      switchRole,
      needsRolePick,
      dismissRolePick,
      logout,
      refreshUser,
      refreshTenant,
    }),
    [accessToken, error, isLoading, login, loginWithRoleHandoff, switchRole, needsRolePick, dismissRolePick, logout, refreshTenant, refreshUser, tenant, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
