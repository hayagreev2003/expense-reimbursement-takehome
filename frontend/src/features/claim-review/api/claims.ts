import { api } from '@/api/client';
import type { components } from '@/api/generated';

export type Claim = components['schemas']['ClaimResponse'];
export type ClaimLine = components['schemas']['ClaimLineResponse'];
export type Employee = components['schemas']['EmployeeResponse'];
export type Trip = components['schemas']['TripSummaryResponse'];

export const fetchEmployees = () => api.get<Employee[]>('/employees');
export const fetchTrips = () => api.get<Trip[]>('/trips');
export const fetchClaim = (trqId: string) => api.get<Claim>(`/trips/${trqId}/claim`);

export const withdrawLine = (trqId: string, description: string) =>
  api.post<Claim>(`/trips/${trqId}/claim/withdraw`, {
    description,
    reason: 'Withdrawn by the employee so the rest of the claim can be submitted.',
  });

export const submitClaim = (trqId: string) =>
  api.post<{ trq_id: string; status: string }>(`/trips/${trqId}/claim/submit`);
