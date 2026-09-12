"""§3.1 - lodging, per night, room tariff excluding taxes."""

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


@rule("LODGING_TARIFF_LIMIT", "§3.1")
def lodging_tariff_limit(line: LineUnderReview, context: EvaluationContext) -> list[Decision]:
    """Excess tariff is a disallowed amount, not an omission.

    The limit is per night and applies to the room tariff *excluding* taxes, so the comparison
    uses gross_amount rather than claimable. Taxes on the tariff are reimbursable in full, and
    folding them in would fail a compliant stay.
    """
    if line.head is not ExpenseHead.LODGING:
        return []

    limits = context.limit("lodging", "limits_per_night") or {}
    limit = limits.get(context.city_class)
    if limit is None:
        return [
            Decision(
                rule_id="LODGING_TARIFF_LIMIT",
                outcome=Outcome.WARNING,
                reason=(
                    f"No lodging limit is defined for city class {context.city_class!r}; "
                    f"this line needs Finance to confirm the classification."
                ),
                citation="§3.1",
            )
        ]

    nights = line.nights or 1
    limit_amount = Decimal(str(limit))
    per_night = (line.gross_amount / nights).quantize(Decimal("0.01"))

    if per_night <= limit_amount:
        return [
            Decision(
                rule_id="LODGING_TARIFF_LIMIT",
                outcome=Outcome.ALLOWED,
                reason=(
                    f"{per_night} per night over {nights} night(s) is within the "
                    f"{context.city_class} limit of {limit_amount}."
                ),
                citation="§3.1",
            )
        ]

    excess = ((per_night - limit_amount) * nights).quantize(Decimal("0.01"))
    return [
        Decision(
            rule_id="LODGING_TARIFF_LIMIT",
            outcome=Outcome.DISALLOWED,
            amount_effect=excess,
            reason=(
                f"{per_night} per night exceeds the {context.city_class} limit of "
                f"{limit_amount}. Excess over {nights} night(s) disallowed: {excess}."
            ),
            citation="§3.1",
        )
    ]
