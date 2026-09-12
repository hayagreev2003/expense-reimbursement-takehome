'use client';

import { ApiError } from '@/api/error';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { useState } from 'react';
import type { DecisionVerb } from '../api/approvals';
import { useRecordDecision } from '../hooks/useApprovals';

/**
 * Approve, return or reject.
 *
 * The decision carries the claim version the approver was shown. If the claim has moved since -
 * someone else acted, or it was returned and resubmitted - the server refuses and says so,
 * rather than writing a decision about a claim that no longer exists in that form.
 */
export function DecisionPanel({
  trqId,
  approverCode,
  version,
}: {
  trqId: string;
  approverCode: string;
  version: number;
}) {
  const decide = useRecordDecision(trqId);
  const [remarks, setRemarks] = useState('');

  const act = (decision: DecisionVerb) =>
    decide.mutate({ decision, approverCode, expectedVersion: version, remarks: remarks.trim() });

  const returningWithoutRemarks = !remarks.trim();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Your decision</CardTitle>
        <p className="text-muted-foreground text-sm">
          Returning sends it back to the employee against the same Travel Request ID (§2.3), so it
          needs a remark saying what to correct.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <Textarea
          placeholder="Remarks — required when returning a claim."
          value={remarks}
          maxLength={1000}
          onChange={event => setRemarks(event.target.value)}
        />

        <div className="flex flex-wrap gap-2">
          <Button disabled={decide.isPending} onClick={() => act('approved')}>
            Approve
          </Button>
          <Button
            variant="outline"
            disabled={decide.isPending || returningWithoutRemarks}
            title={returningWithoutRemarks ? 'Say what needs correcting first' : undefined}
            onClick={() => act('returned')}
          >
            Return for correction
          </Button>
          <Button
            variant="outline"
            className="border-rose-200 text-rose-700 hover:bg-rose-50"
            disabled={decide.isPending}
            onClick={() => act('rejected')}
          >
            Reject
          </Button>
        </div>

        {decide.isSuccess && (
          <Alert className="border-emerald-200 bg-emerald-50">
            <AlertTitle className="text-emerald-900">
              Recorded — the claim is now {decide.data.claim_status.replaceAll('_', ' ')}
            </AlertTitle>
            <AlertDescription className="text-emerald-900">
              {decide.data.claim_status === 'draft'
                ? 'The employee has been notified and can correct and resubmit it.'
                : 'The employee has been notified, and so has whoever it moved to.'}
            </AlertDescription>
          </Alert>
        )}

        {decide.error && (
          <Alert className="border-rose-200 bg-rose-50">
            <AlertTitle className="text-rose-900">Not recorded</AlertTitle>
            <AlertDescription className="text-rose-900">
              {(decide.error as ApiError).userMessage}
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
