'use client';

import { RoleSwitcher } from '@/components/role-switcher';
import { ClaimReview } from '@/features/claim-review/components/claim-review';
import { useTrips } from '@/features/claim-review/hooks/useClaim';

export default function Home() {
  const { data: trips, isLoading } = useTrips();
  const trip = trips?.[0];

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">
      <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
            Nortex Industries Ltd
          </p>
          <p className="text-sm font-medium">Travel expense settlement</p>
        </div>
        <RoleSwitcher />
      </div>

      {isLoading && <p className="text-muted-foreground text-sm">Loading trips…</p>}
      {!isLoading && !trip && (
        <p className="text-muted-foreground text-sm">
          No trips yet. Run <code className="bg-muted rounded px-1">make seed</code>.
        </p>
      )}
      {trip && <ClaimReview trqId={trip.trq_id} />}
    </main>
  );
}
