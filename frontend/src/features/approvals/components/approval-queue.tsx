'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Money } from '@/features/claim-review/components/money';
import Link from 'next/link';
import { useState } from 'react';
import { useApprovalQueue } from '../hooks/useApprovals';

const DECISION_TONE: Record<string, string> = {
  approved: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  returned: 'bg-amber-50 text-amber-900 border-amber-200',
  rejected: 'bg-rose-50 text-rose-800 border-rose-200',
  pending: 'bg-sky-50 text-sky-800 border-sky-200',
};

export function ApprovalQueue() {
  const [scope, setScope] = useState<'pending' | 'acted'>('pending');
  const { data: items, isLoading, error } = useApprovalQueue(scope);

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-3">
        <CardTitle className="text-base">
          {scope === 'pending' ? 'Waiting on you' : 'Decided by you'}
        </CardTitle>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant={scope === 'pending' ? 'default' : 'outline'}
            onClick={() => setScope('pending')}
          >
            Waiting on you
          </Button>
          <Button
            size="sm"
            variant={scope === 'acted' ? 'default' : 'outline'}
            onClick={() => setScope('acted')}
          >
            Decided
          </Button>
        </div>
      </CardHeader>

      <CardContent className="px-0">
        {isLoading && <p className="text-muted-foreground px-6 text-sm">Loading…</p>}
        {error && <p className="px-6 text-sm text-rose-700">{(error as Error).message}</p>}
        {!isLoading && (items ?? []).length === 0 && (
          <p className="text-muted-foreground px-6 text-sm">
            {scope === 'pending'
              ? 'Nothing is waiting on you. A claim appears here the moment it reaches your level.'
              : 'You have not decided anything yet.'}
          </p>
        )}

        {(items ?? []).length > 0 && (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Claim</TableHead>
                  <TableHead>Employee</TableHead>
                  <TableHead>Your level</TableHead>
                  <TableHead className="text-right">Payable</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(items ?? []).map(item => (
                  <TableRow key={item.claim_external_id}>
                    <TableCell>
                      <div className="font-medium">{item.trq_id}</div>
                      <div className="text-muted-foreground text-xs">
                        {item.destination} · {item.from_date} to {item.to_date}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <div>{item.employee_name}</div>
                      <div className="text-muted-foreground text-xs">{item.employee_code}</div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {item.role}
                      <span className="text-muted-foreground"> · step {item.sequence}</span>
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      <Money amount={item.payable} />
                      {item.disallowed_total !== '0.00' && (
                        <div className="text-xs text-rose-700">
                          <Money amount={item.disallowed_total} /> disallowed
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={DECISION_TONE[item.decision] ?? ''}>
                        {item.decision}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button asChild size="sm" variant="outline">
                        <Link href={`/admin/claims/${item.trq_id}`}>Open</Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
