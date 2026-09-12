'use client';

import { AppShell } from '@/components/app-shell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ClaimReview } from '@/features/claim-review/components/claim-review';
import { Money } from '@/features/claim-review/components/money';
import { useTrips } from '@/features/claim-review/hooks/useClaim';
import { DocumentList } from '@/features/evidence/components/document-list';
import { UploadPanel } from '@/features/evidence/components/upload-panel';
import { useRequireProfile } from '@/features/session/hooks/useRequireProfile';
import { useState } from 'react';

/** The employee's side: their trips, their evidence, their claim, and where it has got to. */
export default function EmployeeHome() {
  const { me, isLoading: checking, ready } = useRequireProfile('employee');
  const { data: trips, isLoading } = useTrips();
  const [selected, setSelected] = useState<string | null>(null);

  if (checking || !ready) return null;

  const list = trips ?? [];
  const trip = list.find(item => item.trq_id === selected) ?? list[0];
  const editable = trip?.status === 'draft' || trip?.status === 'ready_to_submit';

  return (
    <AppShell me={me}>
      {isLoading && <p className="text-muted-foreground text-sm">Loading your trips…</p>}

      {!isLoading && list.length === 0 && (
        <p className="text-muted-foreground text-sm">
          No trips yet. Run <code className="bg-muted rounded px-1">make seed</code> to load the
          sample trip.
        </p>
      )}

      {list.length > 1 && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="text-base">Your trips</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {list.map(item => (
              <Button
                key={item.trq_id}
                size="sm"
                variant={item.trq_id === trip?.trq_id ? 'default' : 'outline'}
                onClick={() => setSelected(item.trq_id)}
              >
                {item.trq_id}
                <span className="ml-2">
                  <Money amount={item.payable} />
                </span>
                <Badge variant="outline" className="ml-2">
                  {item.status.replaceAll('_', ' ')}
                </Badge>
              </Button>
            ))}
          </CardContent>
        </Card>
      )}

      {trip && (
        <div className="space-y-6">
          <ClaimReview trqId={trip.trq_id} />
          {editable && <UploadPanel trqId={trip.trq_id} />}
          <DocumentList trqId={trip.trq_id} editable={Boolean(editable)} />
        </div>
      )}
    </AppShell>
  );
}
