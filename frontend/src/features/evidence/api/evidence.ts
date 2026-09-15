import { api } from '@/api/client';
import type { components } from '@/api/generated';

export type EvidenceDocument = components['schemas']['UploadedDocumentResponse'];
export type UploadResult = components['schemas']['UploadDocumentResponse'];
export type Correction = components['schemas']['CorrectDocumentRequest'];
export type CorrectedLine = components['schemas']['CorrectedLineRequest'];

/**
 * The kinds a photographed bill may be declared as. Mirrors DECLARABLE_KINDS on the server.
 *
 * A `.eml` needs none of these: it carries a sender and a subject, which is what the server
 * classifies on.
 */
export const DOCUMENT_KINDS = [
  { value: 'hotel_invoice', label: 'Hotel invoice / folio' },
  { value: 'restaurant_bill', label: 'Restaurant bill' },
  { value: 'cab_receipt', label: 'Cab receipt' },
  { value: 'flight_booking', label: 'Flight ticket' },
] as const;

export const fetchDocuments = (trqId: string) =>
  api.get<EvidenceDocument[]>(`/trips/${trqId}/documents`);

export const isMailFile = (file: File) => /\.eml$/i.test(file.name);

export function uploadDocument(
  trqId: string,
  input: { file: File; docKind?: string; note?: string },
) {
  const form = new FormData();
  form.append('file', input.file);
  // Omitted for a mail, so the server classifies it. Sending a kind would override that, and
  // the employee guessing wrong selects the wrong parser.
  if (input.docKind) form.append('doc_kind', input.docKind);
  if (input.note) form.append('note', input.note);
  return api.postForm<UploadResult>(`/trips/${trqId}/documents`, form);
}

export const removeDocument = (trqId: string, externalId: string) =>
  api.delete<void>(`/trips/${trqId}/documents/${externalId}`);

/**
 * Say what a bill says, when nothing could read it.
 *
 * Answers with the re-evaluated claim, because the figures are only half the point: the caller
 * needs to see what policy made of them, which is where a disallowed line shows up.
 */
export const correctDocument = (trqId: string, externalId: string, body: Correction) =>
  api.post<components['schemas']['ClaimResponse']>(
    `/trips/${trqId}/documents/${externalId}/correction`,
    body,
  );
