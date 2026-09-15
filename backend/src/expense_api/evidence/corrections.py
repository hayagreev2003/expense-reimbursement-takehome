"""Figures the claimant typed in, because the machine could not read them.

A document that needs input blocks submission by design - an unbalanced bill must not become
claim lines on a guess. Without a way to resolve it that block is a dead end: the only move left
is to delete the bill and upload the same unreadable image again. The escape has to be real, and
there are only two honest ones - withdraw the line, or say what the bill says.

This is the second. What it deliberately is *not* is a bypass of policy: corrected figures enter
the pipeline as ordinary extracted items and are drafted, attributed, deduplicated and judged
exactly like read ones. A correction changes what the numbers *are*, never what policy makes of
them, and §3 and §4 still disallow what they always disallowed.

Two properties make it auditable rather than a hole:

- The rows are persisted on the document itself, with `extractor_name` naming the human rather
  than a parser. Every surface that reads the pipeline can therefore tell a typed figure from a
  read one, and the claim says so on the approver's screen.
- The entry is appended to `claim_event` with the figures as submitted, by the router that
  accepts it. The event is what survives a later re-correction; the rows are replaced.
"""

from __future__ import annotations

from collections.abc import Sequence

from expense_api.db.models import EvidenceDocument, ExtractedLineItem, ExtractionStatus
from expense_api.evidence.dedup import fingerprint
from expense_api.evidence.extractors.base import ExtractedItem, ExtractionResult

# Stored in `evidence_document.extractor_name`, where a parser's name would otherwise be. The
# question that column answers - "where did these numbers come from" - has a human as a valid
# answer, and recording it as one is what keeps the distinction visible downstream.
MANUAL_EXTRACTOR = "manual"

# What a claimant may correct. A document whose figures were read and reconciled is not on the
# list: overwriting a balanced extraction by hand is not a correction, it is an unreviewed edit.
CORRECTABLE: frozenset[ExtractionStatus] = frozenset(
    {
        ExtractionStatus.NEEDS_INPUT,
        ExtractionStatus.FAILED,
        # Uploaded and not yet evaluated. The claim is computed on read, so a bill the employee
        # already knows is unreadable can be corrected before anything has looked at it.
        ExtractionStatus.PENDING,
    }
)


def names_a_human(document: EvidenceDocument) -> bool:
    """Whether the figures on this document were typed, judged without reading its rows.

    Separate from `is_manually_entered` so a caller holding a document whose `line_items` were
    not eagerly loaded can still answer the question - in an async session a lazy load raises.
    """
    return document.extractor_name == MANUAL_EXTRACTOR


def is_manually_entered(document: EvidenceDocument) -> bool:
    """Whether this document's figures came from the claimant rather than an extractor."""
    return names_a_human(document) and bool(document.line_items)


def is_correctable(document: EvidenceDocument) -> bool:
    """A correction is allowed on a document nothing could read - or on an earlier correction."""
    return document.extraction_status in CORRECTABLE or is_manually_entered(document)


def apply(document: EvidenceDocument, items: Sequence[ExtractedItem]) -> None:
    """Replace this document's figures with the ones given, and record who they came from.

    Replace, not append: a second correction is the claimant fixing what they typed, and adding
    to it would double the bill. The `claim_event` the router writes is what preserves the
    earlier attempt.
    """
    document.line_items.clear()

    for item in items:
        document.line_items.append(
            ExtractedLineItem(
                merchant=item.merchant,
                txn_date=item.txn_date,
                description=item.description,
                gross_amount=item.gross_amount,
                tax_amount=item.tax_amount,
                nights=item.nights,
                payment_method=item.payment_method,
                bill_no=item.bill_no,
                fingerprint=fingerprint(item),
                confidence=item.confidence,
                raw_span=item.raw_span,
            )
        )

    document.extractor_name = MANUAL_EXTRACTOR
    document.extraction_status = ExtractionStatus.EXTRACTED
    document.needs_input_reason = None


def as_result(document: EvidenceDocument) -> ExtractionResult:
    """The stored correction, in the shape every other extraction arrives in.

    No stated subtotal and no stated total, so nothing is apportioned on top: a figure a person
    read off a bill is what the bill charged, tax included. Quoting a pre-tax subtotal here
    would add the tax a second time.
    """
    return ExtractionResult(
        extractor_name=MANUAL_EXTRACTOR,
        status=ExtractionStatus.EXTRACTED,
        items=[_to_item(row) for row in sorted(document.line_items, key=lambda row: row.id)],
    )


def _to_item(row: ExtractedLineItem) -> ExtractedItem:
    return ExtractedItem(
        gross_amount=row.gross_amount,
        description=row.description or "Entered by hand",
        merchant=row.merchant,
        txn_date=row.txn_date,
        tax_amount=row.tax_amount,
        payment_method=row.payment_method,
        payer_name=row.payer_name,
        bill_no=row.bill_no,
        nights=row.nights,
        confidence=row.confidence or 1.0,
        raw_span=row.raw_span,
    )
