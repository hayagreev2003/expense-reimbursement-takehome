'use client';

import { ProfilePicker } from '@/features/session/components/profile-picker';
import { restoreSession, useSession } from '@/store/session';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { useMe } from '@/features/session/hooks/useSessionQueries';

/**
 * The way in. Two profiles, and the server decides which one you get - see
 * features/session/components/profile-picker.tsx.
 */
export default function Home() {
  const empCode = useSession(state => state.empCode);
  const router = useRouter();
  const { data: me } = useMe();

  useEffect(() => {
    restoreSession();
  }, []);

  useEffect(() => {
    if (empCode && me) router.replace(me.profile === 'admin' ? '/admin' : '/employee');
  }, [empCode, me, router]);

  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-16">
      <div className="mb-10 space-y-2">
        <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
          Nortex Industries Ltd
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">Travel expense settlement</h1>
        <p className="text-muted-foreground max-w-2xl text-sm">
          A trip inbox becomes a policy-checked claim, routed to the approvers its value
          requires. Choose who you are — this stands in for signing in.
        </p>
      </div>

      <ProfilePicker />
    </main>
  );
}
