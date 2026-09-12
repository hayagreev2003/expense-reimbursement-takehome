"""§3.4 - local conveyance, on actuals against a receipt."""

from __future__ import annotations

from expense_api.db.models import ExpenseHead
from expense_api.policy.registry import (
    Decision,
    EvaluationContext,
    LineUnderReview,
    Outcome,
    rule,
)


@rule("CONVEYANCE_ACTUALS", "§3.4")
def conveyance_actuals(line: LineUnderReview, context: EvaluationContext) -> list[Decision]:
    """Reimbursed on actuals with a receipt; airport transfers at both ends are covered.

    There is no cap here, which is the point of recording an explicit ALLOWED decision rather
    than staying silent: an approver looking at a 1,415.02 airport run should see that a rule
    considered it and passed it, not that no rule looked.
    """
    if line.head is not ExpenseHead.TRANSPORT:
        return []

    return [
        Decision(
            rule_id="CONVEYANCE_ACTUALS",
            outcome=Outcome.ALLOWED,
            reason="Local conveyance on actuals against a receipt; no cap applies.",
            citation="§3.4",
        )
    ]
