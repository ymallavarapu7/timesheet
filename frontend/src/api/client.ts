import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';

// Create axios instance
const _apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const apiClient: AxiosInstance = axios.create({
  baseURL: _apiBase,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add token to requests
apiClient.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('accessToken');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Silent token refresh on 401 ──────────────────────────────────
let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (error: unknown) => void;
}> = [];

const processQueue = (error: unknown, token: string | null) => {
  for (const prom of failedQueue) {
    if (token) {
      prom.resolve(token);
    } else {
      prom.reject(error);
    }
  }
  failedQueue = [];
};

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };
    const requestUrl = String(originalRequest?.url || '');
    const isAuthRequest = requestUrl.includes('/auth/login') || requestUrl.includes('/auth/refresh');
    const hadToken = Boolean(originalRequest?.headers?.Authorization);

    // Only attempt refresh on 401 from authenticated, non-auth requests
    if (error.response?.status !== 401 || isAuthRequest || !hadToken || originalRequest._retry) {
      return Promise.reject(error);
    }

    const refreshToken = sessionStorage.getItem('refreshToken');
    if (!refreshToken) {
      sessionStorage.clear();
      const base = (import.meta.env.BASE_URL as string || '/').replace(/\/$/, '');
      window.location.href = `${base}/login`;
      return Promise.reject(error);
    }

    if (isRefreshing) {
      // Another request is already refreshing — queue this one
      return new Promise((resolve, reject) => {
        failedQueue.push({
          resolve: (token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            resolve(apiClient(originalRequest));
          },
          reject,
        });
      });
    }

    isRefreshing = true;
    originalRequest._retry = true;

    try {
      const response = await axios.post(
        `${_apiBase}/auth/refresh`,
        { refresh_token: refreshToken },
      );

      const { access_token, refresh_token: newRefreshToken } = response.data;

      // Write new tokens to storage BEFORE releasing the queue so that
      // any request interceptor that reads sessionStorage picks up the
      // new token, not the expired one.
      sessionStorage.setItem('accessToken', access_token);
      if (newRefreshToken) {
        sessionStorage.setItem('refreshToken', newRefreshToken);
      }

      // Clear the refreshing flag before draining the queue so newly
      // arriving 401s don't get queued behind an already-resolved refresh.
      isRefreshing = false;
      processQueue(null, access_token);

      originalRequest.headers.Authorization = `Bearer ${access_token}`;
      return apiClient(originalRequest);
    } catch (refreshError) {
      isRefreshing = false;
      processQueue(refreshError, null);
      sessionStorage.clear();
      const base = (import.meta.env.BASE_URL as string || '/').replace(/\/$/, '');
      window.location.href = `${base}/login`;
      return Promise.reject(refreshError);
    }
  },
);

export default apiClient;
