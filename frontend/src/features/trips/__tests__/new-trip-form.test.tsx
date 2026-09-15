import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NewTripForm } from '../components/new-trip-form';

const createTrip = vi.fn();

vi.mock('../api/trips', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/trips')>();
  return { ...actual, createTrip: (input: unknown) => createTrip(input) };
});

const renderForm = (ui: ReactElement) =>
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}
    >
      {ui}
    </QueryClientProvider>,
  );

const fill = async (label: string, value: string) => {
  await userEvent.type(
    screen.getByText(label).parentElement!.querySelector('input, textarea')!,
    value,
  );
};

describe('NewTripForm', () => {
  beforeEach(() => {
    createTrip.mockReset();
    createTrip.mockResolvedValue({ trq_id: 'TRQ-2026-0002' });
  });

  it('refuses an empty application and says which field is missing', async () => {
    renderForm(<NewTripForm onCreated={() => {}} onCancel={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));

    expect(await screen.findByText('Where are you going?')).toBeInTheDocument();
    expect(screen.getByText('A line on why the trip is needed.')).toBeInTheDocument();
    expect(createTrip).not.toHaveBeenCalled();
  });

  it('refuses a trip that ends before it begins, next to the field that is wrong', async () => {
    renderForm(<NewTripForm onCreated={() => {}} onCancel={() => {}} />);

    await fill('Destination', 'Pune');
    await fill('Purpose', 'Commissioning review');
    await fill('Leaving on', '2026-08-06');
    await fill('Back on', '2026-08-03');
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));

    expect(await screen.findByText('The trip cannot end before it begins.')).toBeInTheDocument();
    expect(createTrip).not.toHaveBeenCalled();
  });

  it('rejects an advance that is not an amount', async () => {
    renderForm(<NewTripForm onCreated={() => {}} onCancel={() => {}} />);

    await fill('Destination', 'Pune');
    await fill('Purpose', 'Commissioning review');
    await fill('Leaving on', '2026-08-03');
    await fill('Back on', '2026-08-06');
    await fill('Advance requested (optional)', 'twenty thousand');
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));

    expect(await screen.findByText(/An amount in rupees/)).toBeInTheDocument();
    expect(createTrip).not.toHaveBeenCalled();
  });

  it('sends the application and hands the new trip back to the page', async () => {
    const onCreated = vi.fn();
    renderForm(<NewTripForm onCreated={onCreated} onCancel={() => {}} />);

    await fill('Destination', 'Pune');
    await fill('Purpose', 'Commissioning review at the Chakan line');
    await fill('Leaving on', '2026-08-03');
    await fill('Back on', '2026-08-06');
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));

    await waitFor(() => expect(createTrip).toHaveBeenCalledTimes(1));
    expect(createTrip).toHaveBeenCalledWith(
      expect.objectContaining({
        destination_city: 'Pune',
        from_date: '2026-08-03',
        to_date: '2026-08-06',
        city_class: 'Tier 1',
        mode_of_travel: 'Flight',
        // Blank optional fields go as null rather than as an empty string, which the server
        // would store as a visiting company nobody visited.
        visiting_company: null,
        advance_requested: null,
      }),
    );
    expect(onCreated).toHaveBeenCalledWith('TRQ-2026-0002');
  });
});
