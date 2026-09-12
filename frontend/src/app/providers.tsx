'use client';

import { ApiError } from '@/api/error';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

/**
 * Exported so a role switch can evict the previous role's cached queries. An approver must
 * never see a queue built for someone else.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // On for the approver and finance queues, deliberately. Two people can hold the same
      // claim, and a stale queue here is a correctness problem rather than a cosmetic one.
      refetchOnWindowFocus: true,
      retry: (failureCount, error) => {
        // Retrying a 4xx just repeats a request the server already refused.
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
        return failureCount < 2;
      },
    },
  },
});

export function Providers({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
