'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { resetDemo } from '../api/demo';

/**
 * Reset, then drop every cached query.
 *
 * `clear()` rather than `invalidateQueries()`: the reset deletes the claim, its approval steps
 * and its notifications, so a cache that refetched key by key would render the old claim
 * alongside the new draft for however long the slowest request took. There is nothing worth
 * keeping.
 */
export function useResetDemo() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: resetDemo,
    onSuccess: async () => {
      client.clear();
      await client.invalidateQueries();
    },
  });
}
