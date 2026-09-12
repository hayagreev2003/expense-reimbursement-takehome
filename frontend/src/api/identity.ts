/**
 * Who the client is acting as, for the request layer.
 *
 * A tiny mutable module rather than a hook, because `client.ts` is a leaf: if the fetch wrapper
 * imported the store it would import React state, and every module that touches the API would
 * pull the store in behind it. The session store is the only writer.
 *
 * This stands in for authentication, which is deliberately out of scope - see docs/NOTE.md.
 * When a real session arrives, the cookie or bearer token is set here and nothing else changes.
 */

const STORAGE_KEY = 'nortex.emp_code';

let empCode: string | null = null;

export function setRequestIdentity(code: string | null): void {
  empCode = code;
  if (typeof window === 'undefined') return;
  if (code) window.localStorage.setItem(STORAGE_KEY, code);
  else window.localStorage.removeItem(STORAGE_KEY);
}

export function readStoredIdentity(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(STORAGE_KEY);
}

export function identityHeaders(): Record<string, string> {
  return empCode ? { 'X-Emp-Code': empCode } : {};
}
