import axios, { AxiosInstance } from 'axios';

// Create axios instance
export const apiClient: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add token to requests
apiClient.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('accessToken');
  if (token) {
    // Ensure token is used directly (axios will add 'Bearer ' prefix automatically with HTTPBearer)
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401 responses.
// Only clear auth and redirect if the request actually carried a token
// (avoids logout loops when background queries fire with a stale/empty token).
let isRedirecting = false;
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const requestUrl = String(error.config?.url || '');
    const isLoginRequest = requestUrl.includes('/auth/login');
    const hadToken = Boolean(error.config?.headers?.Authorization);

    if (error.response?.status === 401 && !isLoginRequest && hadToken && !isRedirecting) {
      console.warn('[401 Interceptor] Forcing logout. URL:', requestUrl, 'Status:', error.response?.status);
      isRedirecting = true;
      sessionStorage.removeItem('accessToken');
      sessionStorage.removeItem('user');
      sessionStorage.removeItem('tenant');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default apiClient;
