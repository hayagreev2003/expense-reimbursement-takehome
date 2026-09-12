import { api } from '@/api/client';
import type { components } from '@/api/generated';

export type QueueItem = components['schemas']['ApprovalQueueItemResponse'];
export type DecisionResult = components['schemas']['RecordDecisionResponse'];
export type DecisionVerb = 'approved' | 'returned' | 'rejected';

export const fetchQueue = (scope: 'pending' | 'acted') =>
  api.get<QueueItem[]>(`/approvals?scope=${scope}`);

export const recordDecision = (
  trqId: string,
  input: {
    decision: DecisionVerb;
    approverCode: string;
    expectedVersion: number;
    remarks?: string;
  },
) =>
  api.post<DecisionResult>(`/trips/${trqId}/claim/decision`, {
    decision: input.decision,
    approver_code: input.approverCode,
    expected_version: input.expectedVersion,
    remarks: input.remarks ?? null,
  });
