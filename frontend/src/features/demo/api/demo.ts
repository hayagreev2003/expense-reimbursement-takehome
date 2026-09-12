import { api } from '@/api/client';
import type { components } from '@/api/generated';
import { demoResetToken } from '@/app/global_config';

export type ResetDemo = components['schemas']['ResetDemoResponse'];

export const resetDemo = () =>
  api.post<ResetDemo>('/demo/reset', undefined, {
    headers: demoResetToken ? { 'X-Demo-Token': demoResetToken } : {},
  });
