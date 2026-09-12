"""§5.2 - every claim line requires a supporting document."""

from __future__ import annotations

from expense_api.db.models import PaidBy
from expense_api.policy.registry import (
    Decision,
    EvaluationContext,
    LineUnderReview,
    Outcome,
    rule,
)


@rule("PROOF_REQUIRED", "§5.2")
def proof_required(line: LineUnderReview, context: EvaluationContext) -> list[Decision]:
    """ "A claim line without a proof reference is returned."

    Held at submission rather than disallowed: the document usually exists and simply is not
    attached, and disallowing it would cost the employee money for a filing error.

    Company-paid memo rows are exempt. They are not being reimbursed, so there is nothing for a
    proof reference to support.
    """
    if line.paid_by is PaidBy.COMPANY:
        return []

    if line.proof_ref:
        return []

    return [
        Decision(
            rule_id="PROOF_REQUIRED",
            outcome=Outcome.HELD,
            reason=(
                "This line has no supporting document. Policy §5.2 returns any claim line "
                "without a proof reference."
            ),
            citation="§5.2",
        )
    ]
