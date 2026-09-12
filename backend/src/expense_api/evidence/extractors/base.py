"""The extraction contract.

One protocol, two implementations. Everything downstream - dedup, attribution, the policy
engine, the workflow - consumes `ExtractionResult` and knows nothing about which adapter
produced it. That is the point of the seam: the rule-based parsers are tuned to the sender
formats in this pack and will not read an unseen vendor, and the way to fix that is to swap the
adapter, not to rewrite the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from expense_api.db.models import DocKind, ExtractionStatus
from expense_api.evidence.ingest import ParsedEmail
from expense_api.evidence.reconcile import ReconciliationResult, ReconciliationStatus


@dataclass(frozen=True, slots=True)
class ExtractedItem:
    """One line on a bill, before any policy has been applied to it."""

    gross_amount: Decimal
    description: str
    merchant: str | None = None
    txn_date: date | None = None
    txn_datetime: datetime | None = None
    tax_amount: Decimal | None = None
    payment_method: str | None = None
    # Whose expense the evidence says this is. Attribution compares it to the claimant.
    payer_name: str | None = None
    bill_no: str | None = None
    # Lodging only. The §3.1 limit is per night, so the check needs a divisor.
    nights: int | None = None
    # 0.0-1.0. Anything below the adapter's threshold surfaces as needs-input rather than a
    # pre-filled value the employee might not look at twice.
    confidence: float = 1.0
    raw_span: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    extractor_name: str
    status: ExtractionStatus
    items: list[ExtractedItem] = field(default_factory=list)
    stated_subtotal: Decimal | None = None
    stated_total: Decimal | None = None
    reconciliation: ReconciliationResult | None = None
    # Raw OCR, kept so a reconciliation failure can be shown beside the source image.
    ocr_text: str | None = None
    needs_input_reason: str | None = None

    @property
    def extracted_total(self) -> Decimal:
        return sum((item.gross_amount for item in self.items), Decimal("0.00"))

    @property
    def is_usable(self) -> bool:
        if self.status is not ExtractionStatus.EXTRACTED:
            return False
        return self.reconciliation is None or self.reconciliation.is_usable


class Extractor(Protocol):
    """Both adapters emit exactly this."""

    name: str

    def extract(self, parsed: ParsedEmail, kind: DocKind) -> ExtractionResult: ...


def needs_input(
    extractor_name: str,
    reason: str,
    *,
    items: list[ExtractedItem] | None = None,
    reconciliation: ReconciliationResult | None = None,
    ocr_text: str | None = None,
    stated_subtotal: Decimal | None = None,
) -> ExtractionResult:
    """A document a human has to look at before it can become claim lines.

    Whatever was extracted is carried along rather than discarded - the employee correcting it
    needs to see what the machine did read, next to the source.
    """
    return ExtractionResult(
        extractor_name=extractor_name,
        status=ExtractionStatus.NEEDS_INPUT,
        items=items or [],
        stated_subtotal=stated_subtotal,
        reconciliation=reconciliation,
        ocr_text=ocr_text,
        needs_input_reason=reason,
    )


def from_items(
    extractor_name: str,
    items: list[ExtractedItem],
    *,
    stated_subtotal: Decimal | None = None,
    stated_total: Decimal | None = None,
    ocr_text: str | None = None,
    reconcile_amounts: list[Decimal] | None = None,
) -> ExtractionResult:
    """Build a result and run the reconciliation guard over it.

    Every adapter returns through here, so no extraction path can skip the check.

    `reconcile_amounts` overrides what gets summed. It exists because a receipt that states
    only a total would otherwise be "reconciled" against itself, which always passes and proves
    nothing. Where the bill itemises - a cab's fare/surcharge/tax, a restaurant's
    subtotal/GST/service charge - those components are what get checked against the total, even
    though a single line is emitted.
    """
    from expense_api.evidence.reconcile import reconcile

    amounts = (
        reconcile_amounts
        if reconcile_amounts is not None
        else [item.gross_amount for item in items]
    )
    check = reconcile(line_amounts=amounts, stated_subtotal=stated_subtotal)

    if check.status is ReconciliationStatus.MISMATCH:
        return needs_input(
            extractor_name,
            check.message,
            items=items,
            reconciliation=check,
            ocr_text=ocr_text,
            stated_subtotal=stated_subtotal,
        )

    return ExtractionResult(
        extractor_name=extractor_name,
        status=ExtractionStatus.EXTRACTED,
        items=items,
        stated_subtotal=stated_subtotal,
        stated_total=stated_total,
        reconciliation=check,
        ocr_text=ocr_text,
    )
