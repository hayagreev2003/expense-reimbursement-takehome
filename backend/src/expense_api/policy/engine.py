"""Apply the registered rules to a claim's lines.

Every line gets every rule. A rule that does not apply returns nothing; a rule that does
returns decisions carrying its id, its clause, and the amount it removes. Nothing is disallowed
without a reason attached to it, which is the whole point of routing outcomes through decisions
rather than mutating an amount in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from expense_api.db.models import ClaimLineStatus
from expense_api.policy import rules as _rules  # noqa: F401  registers every rule
from expense_api.policy.registry import (
    Decision,
    EvaluationContext,
    LineUnderReview,
    Outcome,
    registered_rules,
)

_ZERO = Decimal("0.00")


@dataclass(slots=True)
class LineOutcome:
    line: LineUnderReview
    status: ClaimLineStatus
    allowed_amount: Decimal
    disallowed_amount: Decimal
    decisions: list[Decision] = field(default_factory=list)

    @property
    def is_held(self) -> bool:
        return self.status is ClaimLineStatus.HELD

    @property
    def blocking_reasons(self) -> list[str]:
        return [d.reason for d in self.decisions if d.outcome is Outcome.HELD]


def evaluate_lines(
    lines: list[LineUnderReview],
    context: EvaluationContext,
    *,
    preset_statuses: dict[int, ClaimLineStatus] | None = None,
) -> list[LineOutcome]:
    """Evaluate every line, in date order for the heads whose caps are cumulative.

    Meal caps are per day across all meals, so a meal line cannot be judged alone - the running
    total in the context is what makes two 900 lunches on one Tier 1 day breach a 1,500 cap
    that neither breaches by itself. Lines are therefore processed oldest first, so the
    accumulation is deterministic rather than dependent on ingestion order.
    """
    presets = preset_statuses or {}
    order = sorted(range(len(lines)), key=lambda i: (lines[i].line_date or date.max, i))

    outcomes: list[LineOutcome | None] = [None] * len(lines)

    for index in order:
        line = lines[index]
        preset = presets.get(index)

        if preset is ClaimLineStatus.REJECTED:
            outcomes[index] = _rejected(line)
            continue
        if preset is ClaimLineStatus.MEMO:
            outcomes[index] = _memo(line)
            continue
        if preset is ClaimLineStatus.WITHDRAWN:
            outcomes[index] = _withdrawn(line)
            continue

        outcome = _evaluate_one(line, context)
        outcomes[index] = outcome

        # Feed this line's allowed meal spend back so the next meal that day sees it.
        if outcome.allowed_amount > _ZERO and line.line_date is not None:
            from expense_api.db.models import ExpenseHead

            if line.head is ExpenseHead.MEALS:
                context.meals_claimed_by_date[line.line_date] = (
                    context.meals_claimed_by_date.get(line.line_date, _ZERO)
                    + outcome.allowed_amount
                )

    return [outcome for outcome in outcomes if outcome is not None]


def _evaluate_one(line: LineUnderReview, context: EvaluationContext) -> LineOutcome:
    decisions: list[Decision] = []
    for _rule_id, _citation, fn in registered_rules():
        decisions.extend(fn(line, context))

    disallowed = sum(
        (d.amount_effect for d in decisions if d.outcome is Outcome.DISALLOWED), _ZERO
    ).quantize(Decimal("0.01"))
    # A rule cannot remove more than the line is worth, however many of them fire.
    disallowed = min(disallowed, line.claimable)

    allowed = (line.claimable - disallowed).quantize(Decimal("0.01"))

    if any(d.outcome is Outcome.HELD for d in decisions):
        # Held lines keep their computed amounts: the employee needs to see what the line is
        # worth while deciding whether to supply what is missing or withdraw it.
        status = ClaimLineStatus.HELD
    elif disallowed >= line.claimable and line.claimable > _ZERO:
        status = ClaimLineStatus.DISALLOWED
    else:
        # Partially disallowed lines stay ALLOWED with a non-zero disallowed amount. The
        # settlement form carries one aggregate disallowed row, not a per-line status.
        status = ClaimLineStatus.ALLOWED

    return LineOutcome(
        line=line,
        status=status,
        allowed_amount=allowed,
        disallowed_amount=disallowed,
        decisions=decisions,
    )


def _rejected(line: LineUnderReview) -> LineOutcome:
    """Someone else's expense. Not disallowed - it was never this claim's to disallow."""
    return LineOutcome(
        line=line,
        status=ClaimLineStatus.REJECTED,
        allowed_amount=_ZERO,
        disallowed_amount=_ZERO,
        decisions=[
            Decision(
                rule_id="THIRD_PARTY_CLAIMANT",
                outcome=Outcome.REJECTED,
                reason=line.preset_reason or "Incurred by someone other than the claimant.",
                citation="§4",
            )
        ],
    )


def _memo(line: LineUnderReview) -> LineOutcome:
    """Company-paid. Recorded for audit and policy checking, never reimbursed (§3.2)."""
    return LineOutcome(
        line=line,
        status=ClaimLineStatus.MEMO,
        allowed_amount=_ZERO,
        disallowed_amount=_ZERO,
        decisions=[
            Decision(
                rule_id="AIR_COMPANY_BORNE",
                outcome=Outcome.INFO,
                reason=(
                    line.preset_reason
                    or "Booked centrally and billed to the company; recorded, not reimbursed."
                ),
                citation="§3.2",
            )
        ],
    )


def _withdrawn(line: LineUnderReview) -> LineOutcome:
    """Removed from the claim by the employee, and still visible with its reason."""
    return LineOutcome(
        line=line,
        status=ClaimLineStatus.WITHDRAWN,
        allowed_amount=_ZERO,
        disallowed_amount=_ZERO,
        decisions=[
            Decision(
                rule_id="LINE_WITHDRAWN",
                outcome=Outcome.INFO,
                reason=line.preset_reason or "Withdrawn from this claim by the employee.",
                citation="§5.2",
            )
        ],
    )
