'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createTrip } from '../api/trips';

/**
 * Applying for a trip adds one to the list the employee screen reads, so that query is
 * invalidated rather than patched: the new trip's status and payable are the server's to say.
 */
export function useCreateTrip() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createTrip,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['trips'] });
    },
  });
}
