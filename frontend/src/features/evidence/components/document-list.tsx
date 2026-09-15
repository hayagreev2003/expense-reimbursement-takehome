'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useState } from 'react';
import { useDocuments, useRemoveDocument } from '../hooks/useEvidence';
import { CorrectionPanel } from './correction-panel';

const STATUS_TONE: Record<string, string> = {
  extracted: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  needs_input: 'bg-amber-50 text-amber-900 border-amber-200',
  not_applicable: 'bg-neutral-100 text-neutral-600 border-neutral-200',
  pending: 'bg-sky-50 text-sky-800 border-sky-200',
  failed: 'bg-rose-50 text-rose-800 border-rose-200',
};

/** Everything attached to the trip, so "did it see my bill?" has a visible answer. */
export function DocumentList({ trqId, editable }: { trqId: string; editable: boolean }) {
  const { data: documents, isLoading } = useDocuments(trqId);
  const remove = useRemoveDocument(trqId);
  // Which document is being corrected. One at a time: two open forms invite entering the same
  // bill twice.
  const [correcting, setCorrecting] = useState<string | null>(null);

  if (isLoading) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Evidence ({documents?.length ?? 0})</CardTitle>
        <p className="text-muted-foreground text-sm">
          The trip inbox plus anything you added. Mailed evidence cannot be deleted — a claim line
          is withdrawn with a reason instead. A bill nothing could read can be entered by hand.
        </p>
      </CardHeader>
      <CardContent className="space-y-2">
        {(documents ?? []).map(document => (
          <div key={document.external_id} className="border-b pb-2 last:border-b-0 last:pb-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs break-all">{document.source_filename}</span>
              <Badge variant="outline">{document.doc_kind.replaceAll('_', ' ')}</Badge>
              <Badge variant="outline" className={STATUS_TONE[document.extraction_status] ?? ''}>
                {document.extraction_status.replaceAll('_', ' ')}
              </Badge>
              {document.uploaded && <Badge variant="secondary">uploaded</Badge>}
              {document.manually_entered && <Badge variant="secondary">entered by hand</Badge>}
              {document.needs_input_reason && (
                <span className="text-xs text-amber-800">{document.needs_input_reason}</span>
              )}

              <span className="ml-auto flex items-center gap-1">
                {editable && document.correctable && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setCorrecting(current =>
                        current === document.external_id ? null : document.external_id,
                      )
                    }
                  >
                    {document.manually_entered ? 'Fix the figures' : 'Enter the figures'}
                  </Button>
                )}
                {editable && document.uploaded && (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(document.external_id)}
                  >
                    Remove
                  </Button>
                )}
              </span>
            </div>

            {correcting === document.external_id && (
              <CorrectionPanel
                trqId={trqId}
                externalId={document.external_id}
                filename={document.source_filename}
                onDone={() => setCorrecting(null)}
              />
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
