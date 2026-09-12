import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import type { Claim } from '../api/claims';
import { Money } from './money';

/** Mirrors rows 44-50 of the settlement form, in the same order and with the same wording. */
export function SettlementSummary({ claim }: { claim: Claim }) {
  const s = claim.summary;
  const rows: Array<[string, string, string?]> = [
    ['Total claim — paid by employee', s.employee_paid_gross],
    ['Less: non-reimbursable / disallowed', s.disallowed_total, 'text-rose-700'],
    ['Net reimbursable claim', s.net_reimbursable],
    ['Less: travel advance drawn', s.advance_drawn],
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Settlement</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {rows.map(([label, amount, tone]) => (
          <div key={label} className="flex justify-between gap-4">
            <span className="text-muted-foreground">{label}</span>
            <Money amount={amount} className={tone} />
          </div>
        ))}

        <Separator className="my-3" />

        <div className="flex justify-between gap-4 text-base font-semibold">
          <span>{s.payable !== '0.00' ? 'Amount payable to employee' : 'Amount recoverable'}</span>
          <Money amount={s.payable !== '0.00' ? s.payable : s.recoverable} />
        </div>

        <Separator className="my-3" />

        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">
            Paid by company
            <span className="block text-xs">Recorded for audit, not reimbursed (§3.2)</span>
          </span>
          <Money amount={s.company_paid_memo} className="text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  );
}
