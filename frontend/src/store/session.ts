'use client';

import { queryClient } from '@/app/providers';
import { readStoredIdentity, setRequestIdentity } from '@/api/identity';
import { create } from 'zustand';

/**
 * Which employee is using the app, and therefore which of the two profiles they see.
 *
 * Stands in for authentication, which is deliberately out of scope - see docs/NOTE.md. The
 * profile itself is never decided here: the server derives it from the employee master and
 * returns it on /me, so the client cannot promote itself to an approver by editing a store.
 */
interface SessionState {
  empCode: string | null;
  /**
   * Whether the stored profile has been read back yet. localStorage does not exist during the
   * server render, so the first client render legitimately knows nothing - and a guard that
   * cannot tell "not signed in" from "not looked yet" bounces every reload to the picker.
   */
  hydrated: boolean;
  signIn: (code: string) => void;
  signOut: () => void;
}

export const useSession = create<SessionState>(set => ({
  empCode: null,
  hydrated: false,
  signIn: code => {
    setRequestIdentity(code);
    // Evict everything the previous profile loaded. An approver must never see a queue that
    // was built for someone else, and React Query would happily serve it from cache.
    queryClient.clear();
    set({ empCode: code });
  },
  signOut: () => {
    setRequestIdentity(null);
    queryClient.clear();
    set({ empCode: null });
  },
}));

/** Restore the last profile on a reload. Idempotent; called from whichever page mounts first. */
export function restoreSession(): void {
  if (useSession.getState().hydrated) return;
  const stored = readStoredIdentity();
  if (stored) setRequestIdentity(stored);
  useSession.setState({ empCode: stored, hydrated: true });
}
