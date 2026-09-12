"""§3.5 - business entertainment, which is not meal allowance."""

from __future__ import annotations

from decimal import Decimal

from expense_api.db.models import ExpenseHead
from expense_api.policy.registry import (
    Decision,
    EvaluationContext,
    LineUnderReview,
    Outcome,
    rule,
)


@rule("ENTERTAINMENT_ATTENDEES", "§3.5")
def entertainment_attendees(line: LineUnderReview, context: EvaluationContext) -> list[Decision]:
    """Requires the names and organisation of attendees.

    Held rather than disallowed: the information exists, it is simply not on the claim yet.
    The employee supplies it, or withdraws the line.
    """
    if line.head is not ExpenseHead.BUSINESS_ENTERTAINMENT:
        return []

    if context.entertainment_attendees:
        return [
            Decision(
                rule_id="ENTERTAINMENT_ATTENDEES",
                outcome=Outcome.ALLOWED,
                reason=("Attendees recorded: " + ", ".join(context.entertainment_attendees) + "."),
                citation="§3.5",
            )
        ]

    return [
        Decision(
            rule_id="ENTERTAINMENT_ATTENDEES",
            outcome=Outcome.HELD,
            reason=(
                "Business entertainment requires the names and organisation of everyone "
                "present. The bill records the covers but not who they were."
            ),
            citation="§3.5",
        )
    ]


@rule("ENTERTAINMENT_PRIOR_APPROVAL", "§3.5")
def entertainment_prior_approval(
    line: LineUnderReview, context: EvaluationContext
) -> list[Decision]:
    """Above INR 2,000 it needs prior approval from the Head of Department.

    Prior means before the spend. Approval obtained afterwards is a different thing, and the
    system does not pretend otherwise - it holds the line and says what is missing.
    """
    if line.head is not ExpenseHead.BUSINESS_ENTERTAINMENT:
        return []

    threshold = context.limit("business_entertainment", "prior_approval_threshold")
    if threshold is None or line.claimable <= Decimal(str(threshold)):
        return []

    role = context.limit("business_entertainment", "prior_approval_role") or "Head of Department"

    if context.entertainment_prior_approval:
        return [
            Decision(
                rule_id="ENTERTAINMENT_PRIOR_APPROVAL",
                outcome=Outcome.ALLOWED,
                reason=f"Prior {role} approval is on file for this entertainment spend.",
                citation="§3.5",
            )
        ]

    return [
        Decision(
            rule_id="ENTERTAINMENT_PRIOR_APPROVAL",
            outcome=Outcome.HELD,
            reason=(
                f"{line.claimable} exceeds the {threshold} threshold for business "
                f"entertainment, which requires prior {role} approval. No such approval is "
                f"attached to this trip."
            ),
            citation="§3.5",
        )
    ]
