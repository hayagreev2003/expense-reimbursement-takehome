'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ResetDemoButton } from '@/features/demo/components/reset-demo-button';
import { NotificationBell } from '@/features/notifications/components/notification-bell';
import type { CurrentUser } from '@/features/session/api/session';
import { useSession } from '@/store/session';
import { useRouter } from 'next/navigation';
import type { ReactNode } from 'react';

/** The frame both profiles share: who you are, what is waiting for you, and the way out. */
export function AppShell({ me, children }: { me: CurrentUser | undefined; children: ReactNode }) {
  const signOut = useSession(state => state.signOut);
  const router = useRouter();

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">
      <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
            Nortex Industries Ltd
          </p>
          <p className="text-sm font-medium">Travel expense settlement</p>
        </div>

        <div className="flex items-center gap-3">
          {me && (
            <div className="text-right">
              <div className="text-sm font-medium">{me.name}</div>
              <div className="text-muted-foreground text-xs">{me.designation}</div>
            </div>
          )}
          {me && (
            <Badge variant="secondary">{me.profile === 'admin' ? 'Approver' : 'Employee'}</Badge>
          )}
          <NotificationBell />
          <ResetDemoButton />
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              signOut();
              router.push('/');
            }}
          >
            Switch profile
          </Button>
        </div>
      </div>

      {children}
    </main>
  );
}
