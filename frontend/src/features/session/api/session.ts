import { api } from '@/api/client';
import type { components } from '@/api/generated';

export type CurrentUser = components['schemas']['CurrentUserResponse'];
export type Employee = components['schemas']['EmployeeResponse'];

export const fetchMe = () => api.get<CurrentUser>('/me');
export const fetchEmployees = () => api.get<Employee[]>('/employees');
