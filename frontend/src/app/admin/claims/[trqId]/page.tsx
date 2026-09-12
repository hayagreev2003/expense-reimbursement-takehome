'use client';

import { AppShell } from '@/components/app-shell';
import { Button } from '@/components/ui/button';
import { DecisionPanel } from '@/features/approvals/components/decision-panel';
import { ClaimReview } from '@/features/claim-review/components/claim-review';
import { useClaim } from '@/features/claim-review/hooks/useClaim';
import { DocumentList } from '@/features/evidence/components/document-list';
import { useRequireProfile } from '@/features/session/hooks/useRequireProfile';
import Link from 'next/link';
import { use } from 'react';

/** One claim, as the approver it is with sees it: everything visible, nothing editable. */
export default function AdminClaimPage({ params }: { params: Promise<{ trqId: string }> }) {
  // Next 16 hands route params as a promise. Typed explicitly rather than through the
  // generated PageProps global, which only exists after a build has written .next/types.
  const { trqId } = use(params);
  const { me, isLoading, ready } = useRequireProfile('admin');
  const { data: claim } = useClaim(trqId);

  if (isLoading || !ready) return null;

  return (
    <AppShell me={me}>
      <div className="mb-4">
        <Button asChild variant="ghost" size="sm">
          <Link href="/admin">← Back to approvals</Link>
        </Button>
      </div>

      <div className="space-y-6">
        <ClaimReview trqId={trqId} readOnly />

        {claim?.awaiting_me && me && typeof claim.version === 'number' && (
          <DecisionPanel trqId={trqId} approverCode={me.emp_code} version={claim.version} />
        )}

        {claim && !claim.awaiting_me && (
          <p className="text-muted-foreground text-sm">
            This claim is not waiting on you. It is {claim.status.replaceAll('_', ' ')}.
          </p>
        )}

        <DocumentList trqId={trqId} editable={false} />
      </div>
    </AppShell>
  );
}
