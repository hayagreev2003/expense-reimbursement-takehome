'use client';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { Claim } from '../api/claims';

const DECISION_TONE: Record<string, string> = {
  approved: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  returned: 'bg-amber-50 text-amber-900 border-amber-200',
  rejected: 'bg-rose-50 text-rose-800 border-rose-200',
  pending: 'bg-sky-50 text-sky-800 border-sky-200',
};

const when = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString('en-IN', {
        day: 'numeric',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
    : null;

/**
 * Who has it, who had it, and what they said.
 *
 * Before submission this is a forecast - the chain the current value resolves to, which
 * changes when the value does. After submission it is the record of the round in progress.
 */
export function ApprovalTimeline({ claim }: { claim: Claim }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {claim.frozen ? 'Approval progress' : 'Approval chain'}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {claim.chain.map(step => (
          <div key={step.sequence} className="border-b pb-2 last:border-b-0 last:pb-0">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-medium">
                  {step.approver_name ?? <span className="text-amber-700">Level skipped</span>}
                </div>
                <div className="text-muted-foreground text-xs">
                  {step.role} · step {step.sequence}
                </div>
              </div>
              {claim.frozen && (
                <Badge variant="outline" className={DECISION_TONE[step.decision] ?? ''}>
                  {step.decision}
                </Badge>
              )}
            </div>
            {step.remarks && (
              <p className="text-muted-foreground mt-1 text-xs italic">“{step.remarks}”</p>
            )}
            {when(step.decided_at) && (
              <p className="text-muted-foreground mt-0.5 text-[11px]">{when(step.decided_at)}</p>
            )}
          </div>
        ))}
        <p className="text-muted-foreground pt-1 text-xs">
          Determined by the claim value after disallowances. Finance verifies every claim (§2.1).
        </p>
      </CardContent>
    </Card>
  );
}
