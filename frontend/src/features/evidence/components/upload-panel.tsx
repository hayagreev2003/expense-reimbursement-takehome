'use client';

import { ApiError } from '@/api/error';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useRef, useState } from 'react';
import { DOCUMENT_KINDS, isMailFile } from '../api/evidence';
import { useUploadDocument } from '../hooks/useEvidence';

/**
 * Adding a bill the inbox never got.
 *
 * For a photograph the kind is chosen rather than guessed: an image carries no sender and no
 * subject, so classification has nothing to work from, and picking the wrong parser produces
 * amounts that look plausible and are wrong - which is worse than asking one question.
 *
 * A forwarded mail is the opposite case. It carries both, so the server classifies it, and
 * asking the employee to declare it would only give them a way to override that wrongly.
 */
export function UploadPanel({ trqId }: { trqId: string }) {
  const upload = useUploadDocument(trqId);
  const [file, setFile] = useState<File | null>(null);
  const [docKind, setDocKind] = useState<string>('');
  const [note, setNote] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);

  const reset = () => {
    setFile(null);
    setNote('');
    setDocKind('');
    if (fileInput.current) fileInput.current.value = '';
  };

  const isMail = file !== null && isMailFile(file);
  const ready = file !== null && (isMail || docKind !== '');

  const submit = () => {
    if (!ready || file === null) return;
    upload.mutate(
      { file, docKind: isMail ? undefined : docKind, note: note.trim() || undefined },
      { onSuccess: reset },
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Add a bill</CardTitle>
        <p className="text-muted-foreground text-sm">
          A photograph or scan of a paper bill (.png, .jpg, .webp, .pdf) or a receipt mail you were
          sent (.eml). It is read, checked against policy and added to the claim below.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <Input
          ref={fileInput}
          type="file"
          accept=".png,.jpg,.jpeg,.webp,.pdf,.eml"
          onChange={event => setFile(event.target.files?.[0] ?? null)}
        />

        {isMail ? (
          <p className="text-muted-foreground text-sm">
            Read from the mail itself — its sender, subject and any attachment it carries.
          </p>
        ) : (
          <Select value={docKind} onValueChange={setDocKind}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="What kind of bill is this?" />
            </SelectTrigger>
            <SelectContent>
              {DOCUMENT_KINDS.map(kind => (
                <SelectItem key={kind.value} value={kind.value}>
                  {kind.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <Textarea
          placeholder="Anything the approver should know — attendees for a hosted meal, for instance."
          value={note}
          maxLength={500}
          onChange={event => setNote(event.target.value)}
        />

        <div className="flex items-center gap-3">
          <Button disabled={!ready || upload.isPending} onClick={submit}>
            {upload.isPending ? 'Reading the bill…' : 'Upload'}
          </Button>
          {upload.isSuccess && (
            <span className="text-sm text-emerald-700">{upload.data.message}</span>
          )}
          {upload.error && (
            <span className="text-sm text-rose-700">
              {(upload.error as ApiError).userMessage ?? 'Upload failed.'}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
