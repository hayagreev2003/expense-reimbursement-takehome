'use client';

import { AppShell } from '@/components/app-shell';
import { ApprovalQueue } from '@/features/approvals/components/approval-queue';
import { useRequireProfile } from '@/features/session/hooks/useRequireProfile';

/** The approver's side: what has been routed to them, and nothing that has not. */
export default function AdminHome() {
  const { me, isLoading, ready } = useRequireProfile('admin');

  if (isLoading || !ready) return null;

  return (
    <AppShell me={me}>
      <div className="mb-6 space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Approvals</h1>
        <p className="text-muted-foreground text-sm">
          A claim reaches you when it reaches your level of the chain, and leaves your queue the
          moment you decide it.
        </p>
      </div>

      <ApprovalQueue />
    </AppShell>
  );
}
