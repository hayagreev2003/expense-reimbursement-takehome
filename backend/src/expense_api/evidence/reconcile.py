"""Check extracted line items against the bill's own stated subtotal.

This is the safety net under both extractors, and it is not a workaround for weak OCR - it is
what a system that moves money should do regardless of how good extraction gets.

The concrete failure it exists for: `pack/receipts/hotel_invoice_1188.png` has a fold drawn
across it, and the fold sits on the second room charge. Tesseract returns the label as
"Spodun-Reom-Cheange." and the amount as "5.750.00". A parser that skips the unreadable line
produces five items summing to 13,450 against a stated subtotal of 19,200 - a claim understated
by 3,750, reported as a success, with nothing anywhere saying so.

Better OCR narrows that gap. It does not close it. So the check lives below the adapters, where
the model-based extractor is covered by it too.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

_ZERO = Decimal("0.00")


class ReconciliationStatus(enum.StrEnum):
    BALANCED = "balanced"
    MISMATCH = "mismatch"
    # No stated subtotal to check against. Most cab receipts give only a total. The absence of
    # a check is recorded as its own state, because it is not the same as a check that passed.
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    status: ReconciliationStatus
    extracted_total: Decimal
    stated_subtotal: Decimal | None
    difference: Decimal | None
    message: str

    @property
    def is_usable(self) -> bool:
        """Whether claim lines may be created from this document without a human first."""
        return self.status is not ReconciliationStatus.MISMATCH


def reconcile(
    *,
    line_amounts: Sequence[Decimal],
    stated_subtotal: Decimal | None,
    tolerance: Decimal = _ZERO,
) -> ReconciliationResult:
    """Compare the sum of extracted lines against what the bill says it totals.

    `tolerance` defaults to exact. Money is stored as integer paise, so exactness is the honest
    default; a caller dealing with a bill that genuinely rounds can widen it by a paisa or two.
    """
    extracted = sum(line_amounts, _ZERO).quantize(Decimal("0.01"))

    if stated_subtotal is None:
        return ReconciliationResult(
            status=ReconciliationStatus.UNVERIFIABLE,
            extracted_total=extracted,
            stated_subtotal=None,
            difference=None,
            message=(
                f"No stated subtotal on this document; {len(line_amounts)} line(s) totalling "
                f"{extracted} could not be checked against it."
            ),
        )

    difference = (extracted - stated_subtotal).quantize(Decimal("0.01"))

    if abs(difference) <= tolerance:
        return ReconciliationResult(
            status=ReconciliationStatus.BALANCED,
            extracted_total=extracted,
            stated_subtotal=stated_subtotal,
            difference=_ZERO,
            message=f"{len(line_amounts)} line(s) reconcile to the stated {stated_subtotal}.",
        )

    # Name the shortfall. "Reconciliation failed" tells whoever has to fix it nothing at all.
    direction = "short of" if difference < 0 else "over"
    return ReconciliationResult(
        status=ReconciliationStatus.MISMATCH,
        extracted_total=extracted,
        stated_subtotal=stated_subtotal,
        difference=difference,
        message=(
            f"Extracted lines total {extracted}, which is {abs(difference)} {direction} the "
            f"stated subtotal of {stated_subtotal}. This document needs a human before any "
            f"claim line is created from it."
        ),
    )
