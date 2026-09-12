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
    },
  });
}

export function useSubmitClaim(trqId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => submitClaim(trqId),
    onSuccess: () => client.invalidateQueries({ queryKey: ['claim', trqId] }),
  });
}
