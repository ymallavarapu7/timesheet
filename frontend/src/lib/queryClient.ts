import { QueryClient } from '@tanstack/react-query';

/**
 * Default query behavior for the whole app:
 *
 * - `staleTime: 30s` — data is considered fresh for 30s. Navigating back to a
 *   page you just left doesn't refetch. Individual queries can override.
 * - `gcTime: 5min` — unused cache entries kept around for 5min so back/forward
 *   navigation feels instant.
 * - `refetchOnWindowFocus: false` — tab switching shouldn't trigger a refetch
 *   storm. Pages that want "always fresh on focus" (e.g. an active inbox) can
 *   opt in locally.
 * - `retry: 1` with a short delay — one retry is enough for transient network
 *   blips; more just delays the error message the user eventually has to see.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
      retryDelay: 500,
    },
    mutations: {
      retry: 0,
    },
  },
});
