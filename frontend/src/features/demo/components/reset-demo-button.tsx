'use client';

import { demoResetEnabled } from '@/app/global_config';
import { Button } from '@/components/ui/button';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { useResetDemo } from '../hooks/useResetDemo';

/**
 * Put the walkthrough back to its starting state.
 *
 * Two-step on purpose. It deletes every claim, for every profile, and a single click next to
 * "Switch profile" is exactly the mistake someone makes halfway through showing the approval
 * queue to a room.
 */
export function ResetDemoButton() {
  const [confirming, setConfirming] = useState(false);
  const reset = useResetDemo();
  const router = useRouter();

  if (!demoResetEnabled) return null;

  if (!confirming) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>
        Reset demo
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-muted-foreground text-xs">Delete all claims?</span>
      <Button
        variant="destructive"
        size="sm"
        disabled={reset.isPending}
        onClick={() =>
          reset.mutate(undefined, {
            onSuccess: () => {
              setConfirming(false);
              // Back to the picker: the profile's own trip list, queue and notifications have
              // all just changed underneath whichever page they were on.
              router.push('/');
            },
          })
        }
      >
        {reset.isPending ? 'Resetting…' : 'Yes, reset'}
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={reset.isPending}
        onClick={() => setConfirming(false)}
      >
        Cancel
      </Button>
      {reset.isError && <span className="text-destructive text-xs">{reset.error.message}</span>}
    </div>
  );
}
