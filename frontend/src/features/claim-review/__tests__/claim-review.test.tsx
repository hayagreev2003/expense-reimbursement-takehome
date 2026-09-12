import { Table, TableBody } from '@/components/ui/table';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Claim, ClaimLine } from '../api/claims';
import { ClaimLineRow } from '../components/claim-line-row';
import { Money } from '../components/money';
import { SettlementSummary } from '../components/settlement-summary';

const line = (over: Partial<ClaimLine> = {}): ClaimLine => ({
  index: 0,
  head: 'Misc',
  description: 'Laundry',
  line_date: '2026-06-17',
  paid_by: 'Employee',
  gross_amount: '450.00',
  tax_share: '54.00',
  allowed_amount: '0.00',
  disallowed_amount: '504.00',
  status: 'disallowed',
  proof_ref: '12_hotel_invoice.eml#hotel_invoice_1188.png',
  nights: null,
  decisions: [
    {
      rule_id: 'NON_REIMBURSABLE_CATEGORY',
      outcome: 'disallowed',
      reason: 'Laundry is not reimbursable under policy §4 (laundry).',
      citation: '§4',
      amount_effect: '504.00',
    },
  ],
  ...over,
});

const renderRow = (l: ClaimLine) =>
  render(
    <Table>
      <TableBody>
        <ClaimLineRow line={l} onWithdraw={() => {}} withdrawing={false} />
      </TableBody>
    </Table>,
  );

describe('Money', () => {
  it('formats with Indian grouping and two decimals', () => {
    render(<Money amount="26388.44" />);
    expect(screen.getByText('26,388.44')).toBeInTheDocument();
  });

  it('renders lakh grouping the way an Indian reader expects', () => {
    render(<Money amount="250000.00" />);
    expect(screen.getByText('2,50,000.00')).toBeInTheDocument();
  });
});

describe('ClaimLineRow', () => {
  it('shows a disallowed line with its reason and clause', () => {
    renderRow(line());

    expect(screen.getByText('Laundry')).toBeInTheDocument();
    expect(screen.getByText('Disallowed')).toBeInTheDocument();
    expect(screen.getByText('504.00')).toBeInTheDocument();
    // The employee must be able to see why, without asking Finance.
    expect(screen.getByText('§4')).toBeInTheDocument();
    expect(screen.getByText(/not reimbursable under policy/)).toBeInTheDocument();
  });

  it('names the source document for every line', () => {
    renderRow(line());
    expect(screen.getByText('12_hotel_invoice.eml#hotel_invoice_1188.png')).toBeInTheDocument();
  });

  it('offers withdraw only on a held line', () => {
    const { unmount } = renderRow(line({ status: 'held', description: 'Dinner, 4 covers' }));
    expect(screen.getByRole('button', { name: 'Withdraw' })).toBeInTheDocument();
    unmount();

    renderRow(line());
    expect(screen.queryByRole('button', { name: 'Withdraw' })).not.toBeInTheDocument();
  });

  it('labels a company-paid line so it does not read as reimbursable', () => {
    renderRow(line({ status: 'memo', description: '6E-6284 PNQ-BLR', paid_by: 'Company' }));
    expect(screen.getByText('Company paid')).toBeInTheDocument();
  });

  it('shows apportioned tax next to the charge it belongs to', () => {
    renderRow(line());
    expect(screen.getByText(/tax/)).toBeInTheDocument();
    expect(screen.getByText('54.00')).toBeInTheDocument();
  });
});

describe('SettlementSummary', () => {
  const claim = {
    summary: {
      employee_paid_gross: '27318.04',
      company_paid_memo: '10556.00',
      disallowed_total: '929.60',
      net_reimbursable: '26388.44',
      advance_drawn: '20000.00',
      payable: '6388.44',
      recoverable: '0.00',
    },
  } as Claim;

  it('renders the settlement form rows in order', () => {
    render(<SettlementSummary claim={claim} />);

    expect(screen.getByText('27,318.04')).toBeInTheDocument();
    expect(screen.getByText('929.60')).toBeInTheDocument();
    expect(screen.getByText('26,388.44')).toBeInTheDocument();
    expect(screen.getByText('6,388.44')).toBeInTheDocument();
  });

  it('shows payable when there is one, not recoverable', () => {
    render(<SettlementSummary claim={claim} />);
    expect(screen.getByText('Amount payable to employee')).toBeInTheDocument();
    expect(screen.queryByText('Amount recoverable')).not.toBeInTheDocument();
  });

  it('switches to recoverable when the advance exceeded the claim', () => {
    const over = {
      summary: { ...claim.summary, payable: '0.00', recoverable: '1500.00' },
    } as Claim;

    render(<SettlementSummary claim={over} />);
    expect(screen.getByText('Amount recoverable')).toBeInTheDocument();
    expect(screen.getByText('1,500.00')).toBeInTheDocument();
  });

  it('marks the company-paid total as not reimbursed', () => {
    render(<SettlementSummary claim={claim} />);
    const memo = screen.getByText(/Recorded for audit, not reimbursed/);
    expect(memo).toBeInTheDocument();
    expect(within(memo.parentElement as HTMLElement).getByText(/Paid by company/)).toBeTruthy();
  });
});
