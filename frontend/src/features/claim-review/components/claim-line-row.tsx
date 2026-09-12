'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { TableCell, TableRow } from '@/components/ui/table';
import type { ClaimLine } from '../api/claims';
import { Money } from './money';

const STATUS_STYLES: Record<string, string> = {
  allowed: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  disallowed: 'bg-rose-50 text-rose-800 border-rose-200',
  held: 'bg-amber-50 text-amber-900 border-amber-200',
  rejected: 'bg-rose-50 text-rose-800 border-rose-200',
  withdrawn: 'bg-neutral-100 text-neutral-600 border-neutral-200',
  memo: 'bg-sky-50 text-sky-800 border-sky-200',
};

const STATUS_LABELS: Record<string, string> = {
  allowed: 'Allowed',
  disallowed: 'Disallowed',
  held: 'Held',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
  memo: 'Company paid',
};

export function ClaimLineRow({
  line,
  onWithdraw,
  withdrawing,
}: {
  line: ClaimLine;
  onWithdraw: (description: string) => void;
  withdrawing: boolean;
}) {
  // Every reason a rule gave, so an approver never has to ask why a figure changed.
  const notes = line.decisions.filter(d =>
    ['disallowed', 'held', 'rejected', 'warning'].includes(d.outcome),
  );

  return (
    <>
      <TableRow className={line.status === 'withdrawn' ? 'opacity-55' : undefined}>
        <TableCell className="align-top">
          <div className="font-medium">{line.description}</div>
          <div className="text-muted-foreground mt-0.5 text-xs">
            {line.head}
            {line.line_date ? ` · ${line.line_date}` : ''}
            {line.nights ? ` · ${line.nights} nights` : ''}
          </div>
          {line.proof_ref && (
            // Template legend line 65: a proof ref names a document, never "attached mail".
            <div className="text-muted-foreground mt-1 font-mono text-[11px] break-all">
              {line.proof_ref}
            </div>
          )}
        </TableCell>

        <TableCell className="align-top text-right">
          <Money amount={line.gross_amount} />
          {line.tax_share !== '0.00' && (
            <div className="text-muted-foreground text-xs">
              + <Money amount={line.tax_share} /> tax
            </div>
          )}
        </TableCell>

        <TableCell className="align-top text-right">
          <Money
            amount={line.allowed_amount}
            className={line.allowed_amount === '0.00' ? 'text-muted-foreground' : ''}
          />
        </TableCell>

        <TableCell className="align-top text-right">
          {line.disallowed_amount !== '0.00' ? (
            <Money amount={line.disallowed_amount} className="text-rose-700" />
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </TableCell>

        <TableCell className="align-top">
          <Badge variant="outline" className={STATUS_STYLES[line.status] ?? ''}>
            {STATUS_LABELS[line.status] ?? line.status}
          </Badge>
          {line.status === 'held' && (
            <div className="mt-2">
              <Button
                size="sm"
                variant="outline"
                disabled={withdrawing}
                onClick={() => onWithdraw(line.description)}
              >
                Withdraw
              </Button>
            </div>
          )}
        </TableCell>
      </TableRow>

      {notes.length > 0 && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={5} className="pt-0">
            <ul className="space-y-1">
              {notes.map(note => (
                <li key={note.rule_id} className="text-muted-foreground flex gap-2 text-xs">
                  <span className="bg-muted rounded px-1.5 py-0.5 font-mono text-[10px]">
                    {note.citation}
                  </span>
                  <span>{note.reason}</span>
                </li>
              ))}
            </ul>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}
