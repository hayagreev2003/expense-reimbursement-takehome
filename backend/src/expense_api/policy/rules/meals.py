"""§3.3 - meals, on actuals up to a daily cap by city class."""

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

_ZERO = Decimal("0.00")


@rule("MEALS_DAILY_CAP", "§3.3")
def meals_daily_cap(line: LineUnderReview, context: EvaluationContext) -> list[Decision]:
    """On actuals up to the limit - not a flat allowance.

    The cap is per day and applies across every meal line on that day, so the running total in
    the context matters: two 900 meals on one Tier 1 day are 1,800 claimed against a 1,500 cap,
    even though neither line breaches it alone.

    Travel days count as full days, so no proration is applied to the first or last day.
    """
    if line.head is not ExpenseHead.MEALS:
        return []

    limits = context.limit("meals", "daily_limits") or {}
    limit = limits.get(context.city_class)
    if limit is None or line.line_date is None:
        return []

    cap = Decimal(str(limit))
    already = context.meals_claimed_by_date.get(line.line_date, _ZERO)
    total_for_day = already + line.claimable

    if total_for_day <= cap:
        return [
            Decision(
                rule_id="MEALS_DAILY_CAP",
                outcome=Outcome.ALLOWED,
                reason=(
                    f"{line.claimable} on {line.line_date:%d %b} is within the "
                    f"{context.city_class} daily meal cap of {cap}"
                    + (f" ({already} already claimed that day)." if already else ".")
                ),
                citation="§3.3",
            )
        ]

    excess = (total_for_day - cap).quantize(Decimal("0.01"))
    return [
        Decision(
            rule_id="MEALS_DAILY_CAP",
            outcome=Outcome.DISALLOWED,
            amount_effect=excess,
            reason=(
                f"Meals on {line.line_date:%d %b} total {total_for_day}, over the "
                f"{context.city_class} daily cap of {cap}. Excess disallowed: {excess}."
            ),
            citation="§3.3",
        )
    ]


@rule("MEALS_BILL_THRESHOLD", "§3.3")
def meals_bill_threshold(line: LineUnderReview, context: EvaluationContext) -> list[Decision]:
    """A bill is required above INR 500."""
    if line.head is not ExpenseHead.MEALS:
        return []

    threshold = context.limit("meals", "bill_required_above")
    if threshold is None or line.claimable <= Decimal(str(threshold)):
        return []

    if line.proof_ref:
        return []

    return [
        Decision(
            rule_id="MEALS_BILL_THRESHOLD",
            outcome=Outcome.HELD,
            reason=(
                f"A meal above {threshold} needs a bill, and no supporting document is "
                f"attached to this line."
            ),
            citation="§3.3",
        )
    ]
