'use client';

import { useQuery } from '@tanstack/react-query';
import { useSession } from '@/store/session';
import { fetchEmployees, fetchMe } from '../api/session';

/** The directory that fills the profile picker. Unauthenticated by design - it is the way in. */
export const useEmployees = () =>
  useQuery({ queryKey: ['employees'], queryFn: fetchEmployees });

/**
 * The signed-in person, as the *server* sees them. The profile comes from here and nowhere
 * else: a client-side guess would be a second source of truth for who may approve.
 */
export function useMe() {
  const empCode = useSession(state => state.empCode);
  return useQuery({
    queryKey: ['me', empCode],
    queryFn: fetchMe,
    enabled: Boolean(empCode),
    staleTime: 5 * 60 * 1000,
  });
}
