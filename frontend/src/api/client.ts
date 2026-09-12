/**
 * The fetch wrapper. A leaf module: it imports no auth, context or hooks, so nothing here can
 * accidentally reach back into React state from a request.
 */

import { apiUrl } from '@/app/global_config';
import { ApiError } from './error';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(apiUrl(path), {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    });
  } catch (cause) {
    // Only a genuine transport failure reaches here. Response-level errors are handled below,
    // which keeps an offline blip from being reported as a server fault.
    throw ApiError.network(cause);
  }

  if (!response.ok) {
    throw await ApiError.fromResponse(response);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
};
