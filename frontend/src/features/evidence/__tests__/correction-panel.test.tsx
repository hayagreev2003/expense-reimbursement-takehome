import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CorrectionPanel } from '../components/correction-panel';

const correctDocument = vi.fn();

vi.mock('../api/evidence', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/evidence')>();
  return {
    ...actual,
    correctDocument: (trqId: string, externalId: string, body: unknown) =>
      correctDocument(trqId, externalId, body),
  };
});

const renderPanel = (ui: ReactElement) =>
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}
    >
      {ui}
    </QueryClientProvider>,
  );

const field = (label: string) =>
  screen.getByText(label).parentElement!.querySelector('input')! as HTMLInputElement;

const panel = (onDone = () => {}) => (
  <CorrectionPanel
    trqId="TRQ-2026-0001"
    externalId="doc-1"
    filename="folio_scan.eml"
    onDone={onDone}
  />
);

describe('CorrectionPanel', () => {
  beforeEach(() => {
    correctDocument.mockReset();
    correctDocument.mockResolvedValue({ lines: [] });
  });

  it('names the document whose figures are being entered', () => {
    renderPanel(panel());
    expect(screen.getByText('folio_scan.eml')).toBeInTheDocument();
  });

  it('will not send a line with no amount', async () => {
    renderPanel(panel());

    await userEvent.type(field('Charge'), 'Room tariff');
    await userEvent.click(screen.getByRole('button', { name: 'Save these figures' }));

    expect(await screen.findByText('An amount, e.g. 5750.00')).toBeInTheDocument();
    expect(correctDocument).not.toHaveBeenCalled();
  });

  it('sends each charge as its own line, with the bill details shared across them', async () => {
    const onDone = vi.fn();
    renderPanel(panel(onDone));

    await userEvent.type(field('Merchant'), 'Lemon Tree Premier');
    await userEvent.type(field('Bill number'), 'LT/1188');
    await userEvent.type(field('Charge'), 'Room tariff, 3 nights');
    await userEvent.type(field('Amount'), '17250.00');
    await userEvent.type(field('Date'), '2026-06-16');
    await userEvent.type(field('Nights'), '3');

    await userEvent.click(screen.getByRole('button', { name: 'Save these figures' }));

    await waitFor(() => expect(correctDocument).toHaveBeenCalledTimes(1));
    expect(correctDocument).toHaveBeenCalledWith('TRQ-2026-0001', 'doc-1', {
      stated_total: null,
      lines: [
        {
          description: 'Room tariff, 3 nights',
          gross_amount: '17250.00',
          txn_date: '2026-06-16',
          // A number, not the string the input holds: §3.1 divides by it.
          nights: 3,
          paid_by: 'Employee',
          merchant: 'Lemon Tree Premier',
          bill_no: 'LT/1188',
        },
      ],
    });
    expect(onDone).toHaveBeenCalled();
  });

  it('adds a second charge, because a folio is more than one line', async () => {
    renderPanel(panel());

    expect(screen.getAllByText('Charge')).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: 'Add another charge' }));
    expect(screen.getAllByText('Charge')).toHaveLength(2);

    // Removing is offered only once there is more than one line to remove.
    await userEvent.click(screen.getByRole('button', { name: 'Remove line 2' }));
    expect(screen.getAllByText('Charge')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Remove line 1' })).not.toBeInTheDocument();
  });
});
