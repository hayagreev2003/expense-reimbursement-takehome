"""§4 - items never reimbursed, even when they appear on a consolidated bill."""

from __future__ import annotations

import re
from decimal import Decimal

from expense_api.policy.registry import (
    Decision,
    EvaluationContext,
    LineUnderReview,
    Outcome,
    rule,
)

_ZERO = Decimal("0.00")


@rule("NON_REIMBURSABLE_CATEGORY", "§4")
def non_reimbursable_category(line: LineUnderReview, context: EvaluationContext) -> list[Decision]:
    """Disallow with a remark. Never drop.

    Template legend line 66 is explicit that these appear as a disallowed amount rather than
    being omitted, and the reason is practical: an employee who cannot see why their 21,504
    folio settled at 20,574.40 will ask Finance, which is the follow-up this system exists to
    remove.

    The tax apportioned to the line goes with it. Reimbursing the GST on a mini bar is the same
    error as reimbursing the mini bar.
    """
    categories: list[str] = context.limit("non_reimbursable", "categories") or []
    description = line.description.lower()

    for category in categories:
        # Word-boundary matched: "bar snack" must not be caught by "mini bar", and a "Barista"
        # line must not be caught by "bar".
        if re.search(rf"\b{re.escape(category.lower())}\b", description):
            return [
                Decision(
                    rule_id="NON_REIMBURSABLE_CATEGORY",
                    outcome=Outcome.DISALLOWED,
                    amount_effect=line.claimable,
                    reason=(
                        f"{line.description} is not reimbursable under policy §4 "
                        f"({category}). Disallowed: {line.gross_amount}"
                        + (f" plus {line.tax_share} of apportioned tax." if line.tax_share else ".")
                    ),
                    citation="§4",
                )
            ]

    return []
