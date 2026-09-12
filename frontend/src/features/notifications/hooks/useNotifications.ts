'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '@/store/session';
import { fetchNotifications, markAllRead, markRead } from '../api/notifications';

/**
 * Polled, not pushed.
 *
 * A claim changes hands a handful of times a week, so a websocket would be a connection to
 * maintain, authenticate and reconnect for an event rate of roughly zero. Fifteen seconds is
 * well inside the time it takes a person to notice anything, and the endpoint is one indexed
 * query. If this ever needs to be instant, the change is server-sent events behind the same
 * hook, not a different UI.
 */
export function useNotifications() {
  const empCode = useSession(state => state.empCode);
  return useQuery({
    queryKey: ['notifications', empCode],
    queryFn: fetchNotifications,
    enabled: Boolean(empCode),
    refetchInterval: 15_000,
  });
}

export function useMarkRead() {
  const client = useQueryClient();
  const empCode = useSession(state => state.empCode);
  return useMutation({
    mutationFn: (externalId: string) => markRead(externalId),
    onSuccess: () => client.invalidateQueries({ queryKey: ['notifications', empCode] }),
  });
}

export function useMarkAllRead() {
  const client = useQueryClient();
  const empCode = useSession(state => state.empCode);
  return useMutation({
    mutationFn: markAllRead,
    onSuccess: () => client.invalidateQueries({ queryKey: ['notifications', empCode] }),
  });
}
