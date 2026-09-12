/**
 * The fetch wrapper. A leaf module: it imports no auth, context or hooks, so nothing here can
 * accidentally reach back into React state from a request. The one thing it does know about is
 * `identityHeaders()`, which is a plain function over a module variable - see api/identity.ts.
 */

import { apiUrl } from '@/app/global_config';
import { ApiError } from './error';
import { identityHeaders } from './identity';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  // FormData sets its own multipart Content-Type, complete with the boundary. Setting one by
  // hand here drops the boundary and the server rejects the upload as malformed.
  const isFormData = typeof FormData !== 'undefined' && init?.body instanceof FormData;

  try {
    response = await fetch(apiUrl(path), {
      ...init,
      headers: {
        ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
        ...identityHeaders(),
        ...(init?.headers ?? {}),
      },
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
  // `init` is for the rare header a route needs and the session does not supply - today only
  // X-Demo-Token. request() merges it last, so it wins over the identity header; keep callers
  // to headers the session does not already own.
  post: <T>(path: string, body?: unknown, init?: RequestInit) =>
    request<T>(path, {
      ...init,
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    }),
  postForm: <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};
