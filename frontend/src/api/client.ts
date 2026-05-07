import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';

// Create axios instance
const _rawBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
// Strip a trailing /api so the env var works whether set to
// "https://acufy.ai" or "https://acufy.ai/api" — endpoint paths
// already include /api/ where needed.
const _apiBase = _rawBase.replace(/\/api\/?$/, '');

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
      // No refresh token — force logout
      sessionStorage.clear();
      window.location.href = '/login';
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

      // Update stored tokens
      sessionStorage.setItem('accessToken', access_token);
      if (newRefreshToken) {
        sessionStorage.setItem('refreshToken', newRefreshToken);
      }

      // Retry queued requests with new token
      processQueue(null, access_token);

      // Retry the original request
      originalRequest.headers.Authorization = `Bearer ${access_token}`;
      return apiClient(originalRequest);
    } catch (refreshError) {
      // Refresh failed — force logout
      processQueue(refreshError, null);
      sessionStorage.clear();
      window.location.href = '/login';
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  },
);

export default apiClient;
