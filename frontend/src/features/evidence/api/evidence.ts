import { api } from '@/api/client';
import type { components } from '@/api/generated';

export type EvidenceDocument = components['schemas']['UploadedDocumentResponse'];
export type UploadResult = components['schemas']['UploadDocumentResponse'];

/** The kinds a photographed bill may be declared as. Mirrors DECLARABLE_KINDS on the server. */
export const DOCUMENT_KINDS = [
  { value: 'hotel_invoice', label: 'Hotel invoice / folio' },
  { value: 'restaurant_bill', label: 'Restaurant bill' },
  { value: 'cab_receipt', label: 'Cab receipt' },
  { value: 'flight_booking', label: 'Flight ticket' },
] as const;

export const fetchDocuments = (trqId: string) =>
  api.get<EvidenceDocument[]>(`/trips/${trqId}/documents`);

export function uploadDocument(
  trqId: string,
  input: { file: File; docKind: string; note?: string },
) {
  const form = new FormData();
  form.append('file', input.file);
  form.append('doc_kind', input.docKind);
  if (input.note) form.append('note', input.note);
  return api.postForm<UploadResult>(`/trips/${trqId}/documents`, form);
}

export const removeDocument = (trqId: string, externalId: string) =>
  api.delete<void>(`/trips/${trqId}/documents/${externalId}`);
