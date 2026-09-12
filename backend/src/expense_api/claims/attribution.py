"""Whose expense is this, and who actually paid for it.

Two questions the evidence answers and the travel request cannot.

**Claimant attribution** (§4, "Expenses incurred by any person other than the claimant").
The pack puts a colleague's cab from a different trip into the claimant's inbox with a note
asking for it to be added. Who forwarded it is irrelevant, and so is which trip it belongs to -
the rider named on the receipt is not the claimant, so it is rejected, and the rejection names
her.

**Paid By** (template legend line 63; the settlement summary's SUMIF keys on this exact word).
Derived from payment evidence, never from the travel request's plan. The sample trip's hotel
was budgeted Company-borne and the booking voucher says "Pay at Hotel"; the invoice shows it
settled on the employee's personal card. Trusting the plan produces the wrong answer.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

from expense_api.db.models import PaidBy

_NON_ALPHA = re.compile(r"[^a-z ]+")

# Honorifics that appear on airline tickets and would otherwise defeat a name comparison.
_TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof"}

# Payment wording that means the company already paid. Checked before the employee signals,
# because "Corporate Card ending 4417" also contains the word "card".
_COMPANY_SIGNALS = ("corporate card", "company card", "billed to company", "company account")
_EMPLOYEE_SIGNALS = ("personal", "guest", "self", "own card")


class Attribution(enum.StrEnum):
    CLAIMANT = "claimant"
    THIRD_PARTY = "third_party"
    # The evidence names nobody. Common and not suspicious - a restaurant bill rarely does.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AttributionResult:
    attribution: Attribution
    payer_name: str | None
    reason: str

    @property
    def is_rejected(self) -> bool:
        return self.attribution is Attribution.THIRD_PARTY


def _tokens(name: str | None) -> set[str]:
    if not name:
        return set()
    cleaned = _NON_ALPHA.sub(" ", name.lower())
    return {part for part in cleaned.split() if part and part not in _TITLES}


def attribute(payer_name: str | None, *, claimant_name: str) -> AttributionResult:
    """Compare the name on the evidence to the claimant.

    Matching on any shared name token rather than the whole string: receipts are inconsistent
    about how much of a name they print. Uber says "Chaitanya", the hotel says "Chaitanya
    Reddy", the airline says "MR CHAITANYA REDDY", and all three are the same person.
    """
    payer_tokens = _tokens(payer_name)
    claimant_tokens = _tokens(claimant_name)

    if not payer_tokens:
        return AttributionResult(
            attribution=Attribution.UNKNOWN,
            payer_name=None,
            reason="This document does not name who paid; attributed to the claimant.",
        )

    if payer_tokens & claimant_tokens:
        return AttributionResult(
            attribution=Attribution.CLAIMANT,
            payer_name=payer_name,
            reason=f"Named payer {payer_name!r} matches the claimant.",
        )

    return AttributionResult(
        attribution=Attribution.THIRD_PARTY,
        payer_name=payer_name,
        reason=(
            f"This expense was incurred by {payer_name}, not by {claimant_name}. "
            f"Policy §4 excludes expenses of any person other than the claimant, so it cannot "
            f"be settled on this claim regardless of who forwarded it."
        ),
    )


def derive_paid_by(payment_method: str | None, *, company_name: str | None = None) -> PaidBy:
    """Company or Employee, from the payment evidence alone.

    Defaults to Employee when the evidence is silent: the employee is the one claiming, and a
    wrongly-Company line silently drops from the reimbursable total, which is the more damaging
    direction to be wrong in.
    """
    if not payment_method:
        return PaidBy.EMPLOYEE

    text = payment_method.lower()

    if any(signal in text for signal in _COMPANY_SIGNALS):
        return PaidBy.COMPANY
    if company_name and company_name.lower() in text:
        return PaidBy.COMPANY
    if any(signal in text for signal in _EMPLOYEE_SIGNALS):
        return PaidBy.EMPLOYEE

    return PaidBy.EMPLOYEE
