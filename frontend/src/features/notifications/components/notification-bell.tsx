'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Bell } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useMarkAllRead, useMarkRead, useNotifications } from '../hooks/useNotifications';

const KIND_TONE: Record<string, string> = {
  awaiting_your_approval: 'bg-amber-50 text-amber-900 border-amber-200',
  claim_submitted: 'bg-sky-50 text-sky-800 border-sky-200',
  claim_approved: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  claim_verified: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  claim_returned: 'bg-amber-50 text-amber-900 border-amber-200',
  claim_rejected: 'bg-rose-50 text-rose-800 border-rose-200',
};

const relative = (iso: string): string => {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
};

export function NotificationBell() {
  const { data } = useNotifications();
  const markRead = useMarkRead();
  const markAllRead = useMarkAllRead();
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);

  // Click-outside rather than a modal: the panel is a peek at a queue, and trapping focus for
  // that is heavier than the interaction deserves.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  const unread = data?.unread_count ?? 0;
  const items = data?.items ?? [];

  return (
    <div className="relative" ref={container}>
      <Button
        variant="outline"
        size="sm"
        aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`}
        onClick={() => setOpen(value => !value)}
      >
        <Bell className="size-4" />
        {unread > 0 && (
          <span className="ml-1.5 rounded-full bg-rose-600 px-1.5 text-[11px] font-semibold text-white">
            {unread}
          </span>
        )}
      </Button>

      {open && (
        <div className="bg-popover absolute right-0 z-30 mt-2 w-[360px] rounded-lg border shadow-lg">
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="text-sm font-medium">Notifications</span>
            <Button
              variant="ghost"
              size="sm"
              disabled={unread === 0 || markAllRead.isPending}
              onClick={() => markAllRead.mutate()}
            >
              Mark all read
            </Button>
          </div>

          <div className="max-h-[420px] overflow-y-auto">
            {items.length === 0 && (
              <p className="text-muted-foreground px-3 py-6 text-center text-sm">Nothing yet.</p>
            )}
            {items.map(item => (
              <button
                key={item.external_id}
                type="button"
                onClick={() => !item.read_at && markRead.mutate(item.external_id)}
                className={`hover:bg-muted/60 block w-full border-b px-3 py-2.5 text-left last:border-b-0 ${
                  item.read_at ? 'opacity-70' : ''
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium">{item.title}</span>
                  {!item.read_at && <span className="mt-1.5 size-2 rounded-full bg-rose-600" />}
                </div>
                <p className="text-muted-foreground mt-0.5 text-xs">{item.body}</p>
                <div className="mt-1.5 flex items-center gap-2">
                  <Badge variant="outline" className={KIND_TONE[item.kind] ?? ''}>
                    {item.kind.replaceAll('_', ' ')}
                  </Badge>
                  {item.created_at && (
                    <span className="text-muted-foreground text-[11px]">
                      {relative(item.created_at)}
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
