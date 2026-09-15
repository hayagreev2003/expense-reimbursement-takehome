'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  correctDocument,
  fetchDocuments,
  removeDocument,
  uploadDocument,
  type Correction,
} from '../api/evidence';

export const useDocuments = (trqId: string) =>
  useQuery({ queryKey: ['documents', trqId], queryFn: () => fetchDocuments(trqId) });

/**
 * An upload changes the claim, so both queries are invalidated together. Invalidating only the
 * document list would leave the employee looking at a bill that is visibly attached and a set
 * of figures that has not moved.
 */
function useEvidenceMutation<TVariables, TData>(
  trqId: string,
  mutationFn: (variables: TVariables) => Promise<TData>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['documents', trqId] });
      client.invalidateQueries({ queryKey: ['claim', trqId] });
      client.invalidateQueries({ queryKey: ['trips'] });
    },
  });
}

export const useUploadDocument = (trqId: string) =>
  useEvidenceMutation(trqId, (input: { file: File; docKind?: string; note?: string }) =>
    uploadDocument(trqId, input),
  );

export const useRemoveDocument = (trqId: string) =>
  useEvidenceMutation(trqId, (externalId: string) => removeDocument(trqId, externalId));

/**
 * Entering a bill's figures by hand.
 *
 * The response is the re-evaluated claim, so it seeds the cache rather than triggering a
 * refetch: a correction can unblock submission and can move the claim into a different approval
 * band, and the employee should see both immediately.
 */
export function useCorrectDocument(trqId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { externalId: string; correction: Correction }) =>
      correctDocument(trqId, input.externalId, input.correction),
    onSuccess: claim => {
      client.setQueryData(['claim', trqId], claim);
      client.invalidateQueries({ queryKey: ['documents', trqId] });
      client.invalidateQueries({ queryKey: ['trips'] });
    },
  });
}
