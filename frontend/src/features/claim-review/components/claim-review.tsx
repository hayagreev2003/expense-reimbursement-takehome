'use client';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useClaim, useSubmitClaim, useWithdrawLine } from '../hooks/useClaim';
import { ClaimLineRow } from './claim-line-row';
import { SettlementSummary } from './settlement-summary';

export function ClaimReview({ trqId }: { trqId: string }) {
  const { data: claim, isLoading, error } = useClaim(trqId);
  const withdraw = useWithdrawLine(trqId);
  const submit = useSubmitClaim(trqId);

  if (isLoading) return <p className="text-muted-foreground p-8 text-sm">Loading the claim…</p>;
  if (error) return <p className="p-8 text-sm text-rose-700">{(error as Error).message}</p>;
  if (!claim) return null;

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{claim.trq_id}</h1>
          <Badge variant="outline">{claim.city_class}</Badge>
        </div>
        <p className="text-muted-foreground text-sm">
          {claim.employee_name} · {claim.destination} · {claim.from_date} to {claim.to_date} · due{' '}
          {claim.submission_deadline}
        </p>
      </header>

      {claim.blocking_reasons.length > 0 && (
        <Alert className="border-amber-200 bg-amber-50">
          <AlertTitle className="text-amber-900">This claim cannot be submitted yet</AlertTitle>
          <AlertDescription>
            <ul className="mt-1 list-disc space-y-1 pl-4 text-amber-900">
              {claim.blocking_reasons.map(reason => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {claim.coverage_gaps.length > 0 && (
        <Alert>
          <AlertTitle>Nothing accounts for {claim.coverage_gaps.join(', ')}</AlertTitle>
          <AlertDescription>
            The trip covers these nights but no accommodation evidence does. Flagged rather than
            filled in — add the missing bill if there is one.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="text-base">Claim lines</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto px-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Line</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead className="text-right">Allowed</TableHead>
                  <TableHead className="text-right">Disallowed</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {claim.lines.map(line => (
                  <ClaimLineRow
                    key={`${line.index}-${line.description}`}
                    line={line}
                    withdrawing={withdraw.isPending}
                    onWithdraw={description => withdraw.mutate(description)}
                  />
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <SettlementSummary claim={claim} />

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Approval chain</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {/* Derived from the value after disallowances, so it changes when the claim does. */}
              {claim.chain.map(step => (
                <div key={step.sequence} className="flex justify-between gap-3">
                  <span className="text-muted-foreground">{step.role}</span>
                  <span className="text-right">
                    {step.approver_name ?? <span className="text-amber-700">skipped</span>}
                  </span>
                </div>
              ))}
              <p className="text-muted-foreground pt-2 text-xs">
                Determined by the claim value after disallowances.
              </p>
            </CardContent>
          </Card>

          <Button
            className="w-full"
            disabled={!claim.can_submit || submit.isPending}
            onClick={() => submit.mutate()}
          >
            {submit.isSuccess ? 'Submitted' : 'Submit claim'}
          </Button>
        </div>
      </div>

      {(claim.set_aside.length > 0 || claim.suppressed_duplicates.length > 0) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Seen and not claimed</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {/* Shown deliberately. An item that is simply absent looks exactly like one that
                was missed, and the employee has no way to tell which happened. */}
            {claim.suppressed_duplicates.map(dup => (
              <div key={dup.reason} className="flex gap-2">
                <Badge variant="outline">duplicate</Badge>
                <span className="text-muted-foreground">{dup.reason}</span>
              </div>
            ))}
            {claim.set_aside.map(doc => (
              <div key={doc.source_filename} className="flex flex-wrap gap-2">
                <Badge variant="outline" className="font-mono text-[11px]">
                  {doc.source_filename}
                </Badge>
                <span className="text-muted-foreground">{doc.reason}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
