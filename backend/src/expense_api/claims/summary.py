"""The settlement summary - rows 44 to 50 of the form.

Deliberately mirrors the template's own arithmetic, so the exported workbook's SUMIF formulas
and this code agree. If they ever diverge, the exported spreadsheet quietly contradicts the
application, and Finance will believe the spreadsheet.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from expense_api.db.models import ClaimLineStatus, PaidBy
from expense_api.policy.engine import LineOutcome

_ZERO = Decimal("0.00")

# Statuses that take no part in the money. Rejected lines were never this claim's to pay;
# withdrawn ones were removed by the employee. Both stay visible with their reason.
_EXCLUDED = {ClaimLineStatus.REJECTED, ClaimLineStatus.WITHDRAWN, ClaimLineStatus.MEMO}


@dataclass(frozen=True, slots=True)
class SettlementSummary:
    employee_paid_gross: Decimal
    company_paid_memo: Decimal
    disallowed_total: Decimal
    net_reimbursable: Decimal
    advance_drawn: Decimal
    payable: Decimal
    recoverable: Decimal

    def __post_init__(self) -> None:
        # Template legend line 67. Both non-zero is arithmetically impossible, and the database
        # has a CHECK constraint saying so - failing here gives a better error than the insert.
        if self.payable > _ZERO and self.recoverable > _ZERO:
            raise ValueError(
                f"payable ({self.payable}) and recoverable ({self.recoverable}) are mutually "
                f"exclusive"
            )


def summarise(outcomes: list[LineOutcome], *, advance_drawn: Decimal = _ZERO) -> SettlementSummary:
    """Aggregate evaluated lines into the figures the form carries."""
    employee_gross = sum(
        (
            outcome.line.claimable
            for outcome in outcomes
            if outcome.line.paid_by is PaidBy.EMPLOYEE and outcome.status not in _EXCLUDED
        ),
        _ZERO,
    ).quantize(Decimal("0.01"))

    company_memo = sum(
        (outcome.line.claimable for outcome in outcomes if outcome.line.paid_by is PaidBy.COMPANY),
        _ZERO,
    ).quantize(Decimal("0.01"))

    disallowed = sum(
        (outcome.disallowed_amount for outcome in outcomes if outcome.status not in _EXCLUDED),
        _ZERO,
    ).quantize(Decimal("0.01"))

    net = (employee_gross - disallowed).quantize(Decimal("0.01"))
    difference = (net - advance_drawn).quantize(Decimal("0.01"))

    return SettlementSummary(
        employee_paid_gross=employee_gross,
        company_paid_memo=company_memo,
        disallowed_total=disallowed,
        net_reimbursable=net,
        advance_drawn=advance_drawn,
        payable=max(difference, _ZERO),
        recoverable=max(-difference, _ZERO),
    )
