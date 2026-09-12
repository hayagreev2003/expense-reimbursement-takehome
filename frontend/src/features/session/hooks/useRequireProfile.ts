'use client';

import { restoreSession, useSession } from '@/store/session';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { useMe } from './useSessionQueries';

/**
 * Gate a page on a profile.
 *
 * Client-side only, and deliberately so: this decides which screen to *show*, not what anyone
 * may do. Every route on the server resolves the caller independently and returns 404 or 403,
 * so bypassing this redirect gets you an empty page and a refused request, not access.
 */
export function useRequireProfile(required: 'employee' | 'admin') {
  const empCode = useSession(state => state.empCode);
  const restored = useSession(state => state.hydrated);
  const router = useRouter();

  // The session lives in localStorage, which does not exist during the server render, so it is
  // read back here. `hydrated` lives in the store rather than in local state so this effect
  // does not set component state during render-commit.
  useEffect(() => {
    restoreSession();
  }, []);

  const { data: me, isLoading, error } = useMe();

  useEffect(() => {
    if (!restored) return;
    if (!empCode || error) {
      router.replace('/');
      return;
    }
    if (me && me.profile !== required) {
      router.replace(me.profile === 'admin' ? '/admin' : '/employee');
    }
  }, [restored, empCode, error, me, required, router]);

  return { me, isLoading: !restored || isLoading, ready: Boolean(me && me.profile === required) };
}
