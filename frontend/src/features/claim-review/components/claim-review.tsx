'use client';

import { ApiError } from '@/api/error';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useClaim, useSubmitClaim, useWithdrawLine } from '../hooks/useClaim';
import { ApprovalTimeline } from './approval-timeline';
import { ClaimLineRow } from './claim-line-row';
import { SettlementSummary } from './settlement-summary';

const STATUS_LABELS: Record<string, string> = {
  draft: 'Draft',
  pending_approval: 'With approver',
  pending_finance: 'With Finance',
  verified: 'Verified for payment',
  scheduled_for_payment: 'Scheduled for payment',
  paid: 'Paid',
  rejected: 'Rejected',
};

const STATUS_TONE: Record<string, string> = {
  draft: 'bg-neutral-100 text-neutral-700 border-neutral-200',
  pending_approval: 'bg-sky-50 text-sky-800 border-sky-200',
  pending_finance: 'bg-sky-50 text-sky-800 border-sky-200',
  verified: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  paid: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  rejected: 'bg-rose-50 text-rose-800 border-rose-200',
};

/**
 * One claim, in full.
 *
 * The same component serves both profiles. `readOnly` is what separates them: an approver sees
 * every figure and every reason, and can change none of them - correcting a claim is the
 * employee's job, after a return.
 */
export function ClaimReview({ trqId, readOnly = false }: { trqId: string; readOnly?: boolean }) {
  const { data: claim, isLoading, error } = useClaim(trqId);
  const withdraw = useWithdrawLine(trqId);
  const submit = useSubmitClaim(trqId);

  if (isLoading) return <p className="text-muted-foreground p-8 text-sm">Loading the claim…</p>;
  if (error) return <p className="p-8 text-sm text-rose-700">{(error as Error).message}</p>;
  if (!claim) return null;

  // A frozen claim is the persisted one. Nothing about it can be edited from here, whoever is
  // looking: the employee's route back in is a return from an approver.
  const editable = !readOnly && !claim.frozen;

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{claim.trq_id}</h1>
          <Badge variant="outline" className={STATUS_TONE[claim.status] ?? ''}>
            {STATUS_LABELS[claim.status] ?? claim.status}
          </Badge>
          <Badge variant="outline">{claim.city_class}</Badge>
          {claim.return_count > 0 && (
            <Badge variant="outline" className="bg-amber-50 text-amber-900">
              returned {claim.return_count}×
            </Badge>
          )}
        </div>
        <p className="text-muted-foreground text-sm">
          {claim.employee_name} · {claim.destination} · {claim.from_date} to {claim.to_date} · due{' '}
          {claim.submission_deadline}
        </p>
      </header>

      {editable && claim.blocking_reasons.length > 0 && (
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

      {claim.needs_input.length > 0 && (
        <Alert className="border-amber-200 bg-amber-50">
          <AlertTitle className="text-amber-900">Some evidence needs a human</AlertTitle>
          <AlertDescription>
            <ul className="mt-1 space-y-1 text-amber-900">
              {claim.needs_input.map(document => (
                <li key={document.source_filename}>
                  <span className="font-mono text-xs">{document.source_filename}</span> —{' '}
                  {document.reason}
                </li>
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

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="text-base">Claim lines</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto px-0">
            {/* table-fixed with explicit widths: with auto layout the long route
                descriptions set the table width and the last two columns fall outside
                the card. */}
            <Table className="table-fixed">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[42%]">Line</TableHead>
                  <TableHead className="w-[15%] text-right">Amount</TableHead>
                  <TableHead className="w-[15%] text-right">Allowed</TableHead>
                  <TableHead className="w-[15%] text-right">Disallowed</TableHead>
                  <TableHead className="w-[13%]">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {claim.lines.map(line => (
                  <ClaimLineRow
                    key={`${line.index}-${line.description}`}
                    line={line}
                    withdrawing={withdraw.isPending}
                    onWithdraw={description => withdraw.mutate(description)}
                    editable={editable}
                  />
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <SettlementSummary claim={claim} />
          <ApprovalTimeline claim={claim} />

          {editable && (
            <div className="space-y-2">
              <Button
                className="w-full"
                disabled={!claim.can_submit || submit.isPending}
                onClick={() => submit.mutate()}
              >
                {submit.isPending ? 'Submitting…' : 'Submit claim'}
              </Button>
              {submit.error && (
                <p className="text-sm text-rose-700">{(submit.error as ApiError).userMessage}</p>
              )}
            </div>
          )}
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
