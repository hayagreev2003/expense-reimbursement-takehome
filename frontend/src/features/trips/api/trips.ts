import { api } from '@/api/client';
import type { components } from '@/api/generated';

export type NewTrip = components['schemas']['CreateTripRequest'];
export type Trip = components['schemas']['TripSummaryResponse'];

/** City classes decide which §3.1 lodging limit applies, so the wording matches the policy. */
export const CITY_CLASSES = [
  { value: 'Tier 1', label: 'Tier 1 — metro (Mumbai, Delhi, Bengaluru…)' },
  { value: 'Tier 2', label: 'Tier 2 — Pune, Jaipur, Kochi…' },
  { value: 'Tier 3', label: 'Tier 3 — everywhere else' },
] as const;

export const TRAVEL_MODES = ['Flight', 'Train', 'Bus', 'Cab', 'Self-drive'] as const;

export const createTrip = (input: NewTrip) => api.post<Trip>('/trips', input);
