import React, { createContext, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import axios from 'axios';

import { authAPI, ingestionAPI, mailboxesAPI, tenantsAPI } from '@/api/endpoints';
import { queryClient } from '@/lib/queryClient';
import type { Tenant, User } from '@/types';

interface AuthContextType {
  user: User | null;
  tenant: Tenant | null;
  accessToken: string | null;
  isLoading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<User>;
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

const readStorageObject = <T,>(key: string): T | null => {
  const raw = sessionStorage.getItem(key);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    sessionStorage.removeItem(key);
    return null;
  }
};

const createTenantFallback = (user: User): Tenant | null => {
  if (!user.tenant_id) return null;
  // Try to preserve the name from a previously cached tenant in localStorage
  const cached = readStorageObject<Tenant>('tenant');
  const name = (cached && cached.id === user.tenant_id && cached.name) ? cached.name : 'Workspace';
  return {
    id: user.tenant_id,
    name,
    slug: cached?.slug || `tenant-${user.tenant_id}`,
    status: 'active',
    ingestion_enabled: cached?.ingestion_enabled ?? false,
    created_at: cached?.created_at || '',
    updated_at: cached?.updated_at || '',
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
  const sessionVersionRef = useRef(0);

  const persistAuthState = useCallback((nextUser: User | null, nextTenant: Tenant | null, nextToken: string | null) => {
    if (nextUser) sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(nextUser));
    else sessionStorage.removeItem(USER_STORAGE_KEY);

    if (nextTenant) sessionStorage.setItem(TENANT_STORAGE_KEY, JSON.stringify(nextTenant));
    else sessionStorage.removeItem(TENANT_STORAGE_KEY);

    if (nextToken) sessionStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
    else sessionStorage.removeItem(TOKEN_STORAGE_KEY);
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
      persistAuthState(userToUse ?? null, null, accessToken);
      return;
    }

    try {
      // Use /tenants/mine for regular users (works for all roles),
      // fall back to /tenants/{id} for PLATFORM_ADMIN
      const response = userToUse.role === 'PLATFORM_ADMIN'
        ? await tenantsAPI.get(userToUse.tenant_id)
        : await tenantsAPI.mine();
      setTenant(response.data);
      persistAuthState(userToUse, response.data, accessToken);
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
      persistAuthState(userToUse, fallback, accessToken);
    }
  }, [accessToken, persistAuthState, user]);

  const refreshUser = useCallback(async () => {
    if (!accessToken) return;
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
      return nextUser;
    } catch (err: unknown) {
      const message = extractErrorMessage(err);
      setError(message);
      throw new Error(message);
    } finally {
      setIsLoading(false);
    }
  }, [persistAuthState]);

  // Restore session from localStorage on mount. Use a ref to call the
  // latest refreshUser without adding it to the dependency array (which
  // would cause infinite re-renders as refreshUser is recreated on every
  // state change).
  const refreshUserRef = useRef(refreshUser);
  refreshUserRef.current = refreshUser;

  useEffect(() => {
    const savedUser = readStorageObject<User>(USER_STORAGE_KEY);
    const savedTenant = readStorageObject<Tenant>(TENANT_STORAGE_KEY);
    const savedToken = sessionStorage.getItem(TOKEN_STORAGE_KEY);
    const savedRefreshToken = sessionStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);

    if (!savedToken && !savedRefreshToken) {
      setIsLoading(false);
      return;
    }

    if (savedToken && savedUser) {
      setUser(savedUser);
      setTenant(savedTenant);
      setAccessToken(savedToken);
      setIsLoading(false);
      void refreshUserRef.current();
      return;
    }

    // No access token but have refresh token — attempt silent refresh
    if (savedRefreshToken) {
      axios.post(`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/auth/refresh`, {
        refresh_token: savedRefreshToken,
      }).then((res) => {
        const { access_token, refresh_token: newRefresh } = res.data;
        sessionStorage.setItem(TOKEN_STORAGE_KEY, access_token);
        if (newRefresh) sessionStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, newRefresh);
        setAccessToken(access_token);
        return axios.get(`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/auth/me`, {
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
      logout,
      refreshUser,
      refreshTenant,
    }),
    [accessToken, error, isLoading, login, logout, refreshTenant, refreshUser, tenant, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
