'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '@/store/session';
import { fetchQueue, recordDecision, type DecisionVerb } from '../api/approvals';

export function useApprovalQueue(scope: 'pending' | 'acted') {
  const empCode = useSession(state => state.empCode);
  return useQuery({
    queryKey: ['approvals', empCode, scope],
    queryFn: () => fetchQueue(scope),
    enabled: Boolean(empCode),
    // Two people can hold the same claim at different levels, so a queue that is quietly out
    // of date is a correctness problem rather than a cosmetic one.
    refetchInterval: 30_000,
  });
}

export function useRecordDecision(trqId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      decision: DecisionVerb;
      approverCode: string;
      expectedVersion: number;
      remarks?: string;
    }) => recordDecision(trqId, input),
    onSuccess: () => {
      // Everything moves at once: the claim's status, both queues, the trip list, and the
      // notification the decision just generated.
      client.invalidateQueries({ queryKey: ['claim', trqId] });
      client.invalidateQueries({ queryKey: ['approvals'] });
      client.invalidateQueries({ queryKey: ['trips'] });
      client.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
}
