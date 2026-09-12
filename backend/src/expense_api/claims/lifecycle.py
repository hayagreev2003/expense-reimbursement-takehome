"""Claim state, submission gating, deadlines and payment runs.

The transition table is explicit rather than implied by scattered `if status ==` checks,
because the interesting states here are the ones that go backwards: a returned claim reverts to
draft against the same Travel Request ID (§2.3), and everything approved before it changed has
to stop counting.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from expense_api.db.models import ClaimLineStatus, ClaimStatus
from expense_api.policy.engine import LineOutcome

# What may follow what. Anything not listed is refused, so an unexpected transition is an error
# rather than a claim quietly in a state nothing handles.
TRANSITIONS: dict[ClaimStatus, frozenset[ClaimStatus]] = {
    ClaimStatus.DRAFT: frozenset({ClaimStatus.PENDING_APPROVAL}),
    ClaimStatus.PENDING_APPROVAL: frozenset(
        {
            ClaimStatus.PENDING_APPROVAL,  # next level in the chain
            ClaimStatus.PENDING_FINANCE,
            ClaimStatus.DRAFT,  # returned with remarks
            ClaimStatus.REJECTED,
        }
    ),
    ClaimStatus.PENDING_FINANCE: frozenset(
        {ClaimStatus.VERIFIED, ClaimStatus.DRAFT, ClaimStatus.REJECTED}
    ),
    ClaimStatus.VERIFIED: frozenset({ClaimStatus.SCHEDULED_FOR_PAYMENT}),
    ClaimStatus.SCHEDULED_FOR_PAYMENT: frozenset({ClaimStatus.PAID}),
    ClaimStatus.PAID: frozenset(),
    ClaimStatus.REJECTED: frozenset(),
}


class TransitionError(Exception):
    """An attempt to move a claim somewhere it cannot go from where it is."""


@dataclass(frozen=True, slots=True)
class SubmissionCheck:
    can_submit: bool
    blocking_reasons: list[str]


def check_can_submit(outcomes: list[LineOutcome]) -> SubmissionCheck:
    """A claim cannot be submitted while any line is held.

    Held means something is genuinely missing - attendee names, a prior approval, a bill - and
    sending it up the chain would ask an approver to sign off on an incomplete claim. The
    employee's way out is to supply what is missing or to withdraw the line, which is recorded
    rather than deleted.
    """
    reasons: list[str] = []

    for outcome in outcomes:
        if outcome.status is ClaimLineStatus.HELD:
            for reason in outcome.blocking_reasons:
                reasons.append(f"{outcome.line.description}: {reason}")

    if not any(
        outcome.status
        not in {ClaimLineStatus.REJECTED, ClaimLineStatus.WITHDRAWN, ClaimLineStatus.MEMO}
        for outcome in outcomes
    ):
        reasons.append("This claim has no reimbursable lines to submit.")

    return SubmissionCheck(can_submit=not reasons, blocking_reasons=reasons)


def assert_transition(current: ClaimStatus, target: ClaimStatus) -> None:
    if target not in TRANSITIONS.get(current, frozenset()):
        raise TransitionError(f"A claim cannot go from {current.value} to {target.value}")


def submission_deadline(return_date: date, *, days: int = 7) -> date:
    """§5.1: within 7 calendar days of return. Calendar, not working, days."""
    return return_date + timedelta(days=days)


def next_payment_run(after: date, *, run_days: list[int] | None = None) -> date:
    """§5.4: verified claims go out on the 10th and the 25th.

    On a run day itself the claim makes that day's run - verification completing that morning
    should not wait a fortnight.
    """
    days = sorted(run_days or [10, 25])

    for day in days:
        if day >= after.day and day <= calendar.monthrange(after.year, after.month)[1]:
            return date(after.year, after.month, day)

    # Past the last run of this month: the first run of the next one.
    year = after.year + (1 if after.month == 12 else 0)
    month = 1 if after.month == 12 else after.month + 1
    return date(year, month, days[0])


def is_overdue(*, return_date: date, submitted_at: date | None, today: date, days: int = 7) -> bool:
    deadline = submission_deadline(return_date, days=days)
    return (submitted_at or today) > deadline


@dataclass(frozen=True, slots=True)
class AdvanceCheck:
    within_policy: bool
    message: str


def check_advance_against_estimate(
    *, advance: Decimal, employee_borne_estimate: Decimal, max_fraction: float
) -> AdvanceCheck:
    """§1.2: an advance may be up to 60% of the estimated employee-borne cost.

    A warning, not a block. The sample trip's request draws 20,000 against an employee-borne
    estimate of 10,000, which is over - and it is over because the plan put lodging on the
    company and the employee ended up paying it. Worth surfacing, not worth refusing.
    """
    if employee_borne_estimate <= Decimal("0.00"):
        return AdvanceCheck(
            within_policy=False,
            message="No employee-borne cost was estimated, so the advance cannot be checked.",
        )

    ceiling = (employee_borne_estimate * Decimal(str(max_fraction))).quantize(Decimal("0.01"))
    if advance <= ceiling:
        return AdvanceCheck(
            within_policy=True,
            message=f"Advance of {advance} is within {ceiling} ({max_fraction:.0%} of estimate).",
        )

    return AdvanceCheck(
        within_policy=False,
        message=(
            f"Advance of {advance} exceeds {ceiling}, which is {max_fraction:.0%} of the "
            f"estimated employee-borne cost of {employee_borne_estimate} (§1.2)."
        ),
    )
