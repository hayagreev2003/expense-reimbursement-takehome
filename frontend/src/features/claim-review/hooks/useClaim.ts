'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchClaim, fetchEmployees, fetchTrips, submitClaim, withdrawLine } from '../api/claims';

export const useEmployees = () => useQuery({ queryKey: ['employees'], queryFn: fetchEmployees });

export const useTrips = () => useQuery({ queryKey: ['trips'], queryFn: fetchTrips });

export const useClaim = (trqId: string) =>
  useQuery({ queryKey: ['claim', trqId], queryFn: () => fetchClaim(trqId) });

export function useWithdrawLine(trqId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (description: string) => withdrawLine(trqId, description),
    // The response is the re-evaluated claim, so seed the cache with it rather than refetching:
    // withdrawing can change the approval chain, and the user should see that immediately.
    onSuccess: claim => {
      client.setQueryData(['claim', trqId], claim);
      client.invalidateQueries({ queryKey: ['trips'] });
      client.invalidateQueries({ queryKey: ['documents', trqId] });
    },
  });
}

export function useSubmitClaim(trqId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => submitClaim(trqId),
    // Everything the submission moved, not only the claim. The trip's status is what the
    // employee screen reads to decide whether the claim is still editable, so invalidating the
    // claim alone leaves an upload panel on screen for a claim the server will now refuse.
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['claim', trqId] });
      client.invalidateQueries({ queryKey: ['trips'] });
      client.invalidateQueries({ queryKey: ['documents', trqId] });
      client.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
}
