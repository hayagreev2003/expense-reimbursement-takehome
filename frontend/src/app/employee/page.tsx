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
import { NewTripForm } from '@/features/trips/components/new-trip-form';
import { useState } from 'react';

/** The employee's side: their trips, their evidence, their claim, and where it has got to. */
export default function EmployeeHome() {
  const { me, isLoading: checking, ready } = useRequireProfile('employee');
  const { data: trips, isLoading } = useTrips();
  const [selected, setSelected] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  if (checking || !ready) return null;

  const list = trips ?? [];
  const trip = list.find(item => item.trq_id === selected) ?? list[0];
  const editable = trip?.status === 'draft' || trip?.status === 'ready_to_submit';

  // The new trip is selected on the way in, so the next thing on screen is its empty claim and
  // the upload panel - which is what the employee came to do.
  const applied = (trqId: string) => {
    setSelected(trqId);
    setApplying(false);
  };

  return (
    <AppShell me={me}>
      {isLoading && <p className="text-muted-foreground text-sm">Loading your trips…</p>}

      {!isLoading && (
        <div className="mb-6 space-y-4">
          {list.length === 0 && !applying && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">No trips yet</CardTitle>
                <p className="text-muted-foreground text-sm">
                  Apply for a trip to start a claim. The bills can arrive afterwards — mailed
                  receipts land in the trip inbox, and anything on paper you can photograph and
                  upload.
                </p>
              </CardHeader>
              <CardContent>
                <Button onClick={() => setApplying(true)}>Apply for a trip</Button>
              </CardContent>
            </Card>
          )}

          {list.length > 0 && (
            <Card>
              <CardHeader className="flex flex-row items-start justify-between gap-4">
                <div>
                  <CardTitle className="text-base">Your trips</CardTitle>
                  <p className="text-muted-foreground text-sm">
                    Pick the trip you are claiming against.
                  </p>
                </div>
                {!applying && (
                  <Button size="sm" onClick={() => setApplying(true)}>
                    Apply for a trip
                  </Button>
                )}
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
                    {/* `outline` on the selected button is dark text on the dark active fill,
                        which reads as a black blob. */}
                    <Badge
                      variant={item.trq_id === trip?.trq_id ? 'secondary' : 'outline'}
                      className="ml-2"
                    >
                      {item.status.replaceAll('_', ' ')}
                    </Badge>
                  </Button>
                ))}
              </CardContent>
            </Card>
          )}

          {applying && <NewTripForm onCreated={applied} onCancel={() => setApplying(false)} />}
        </div>
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
