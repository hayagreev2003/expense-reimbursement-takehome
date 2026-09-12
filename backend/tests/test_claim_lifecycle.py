"""Unit 7: claim state, submission gating, deadlines and payment runs."""

from datetime import date
from decimal import Decimal

import pytest

from expense_api.claims.lifecycle import (
    TransitionError,
    assert_transition,
    check_advance_against_estimate,
    check_can_submit,
    is_overdue,
    next_payment_run,
    submission_deadline,
)
from expense_api.db.models import ClaimLineStatus, ClaimStatus, ExpenseHead, PaidBy
from expense_api.policy.engine import LineOutcome
from expense_api.policy.registry import Decision, LineUnderReview, Outcome

_ZERO = Decimal("0.00")


def _outcome(status: ClaimLineStatus, *, held_reason: str | None = None) -> LineOutcome:
    line = LineUnderReview(
        head=ExpenseHead.BUSINESS_ENTERTAINMENT,
        description="Dinner, 4 covers",
        gross_amount=Decimal("2255.00"),
        paid_by=PaidBy.EMPLOYEE,
    )
    decisions = []
    if held_reason:
        decisions.append(
            Decision(
                rule_id="ENTERTAINMENT_ATTENDEES",
                outcome=Outcome.HELD,
                reason=held_reason,
                citation="§3.5",
            )
        )
    return LineOutcome(
        line=line,
        status=status,
        allowed_amount=Decimal("2255.00") if status is ClaimLineStatus.ALLOWED else _ZERO,
        disallowed_amount=_ZERO,
        decisions=decisions,
    )


# ------------------------------------------------------------------ submission


def test_a_held_line_blocks_submission() -> None:
    """Sending it up would ask an approver to sign off an incomplete claim."""
    check = check_can_submit(
        [
            _outcome(ClaimLineStatus.ALLOWED),
            _outcome(ClaimLineStatus.HELD, held_reason="Attendee names are missing."),
        ]
    )

    assert not check.can_submit
    assert any("Attendee names" in reason for reason in check.blocking_reasons)
    # The reason names the line, so the employee knows which one to fix.
    assert any("Dinner" in reason for reason in check.blocking_reasons)


def test_withdrawing_the_held_line_unblocks_submission() -> None:
    """The employee's way out. Recorded as withdrawn, not deleted."""
    check = check_can_submit(
        [_outcome(ClaimLineStatus.ALLOWED), _outcome(ClaimLineStatus.WITHDRAWN)]
    )

    assert check.can_submit
    assert check.blocking_reasons == []


def test_a_claim_of_only_rejected_lines_cannot_be_submitted() -> None:
    check = check_can_submit([_outcome(ClaimLineStatus.REJECTED)])

    assert not check.can_submit
    assert any("no reimbursable lines" in r for r in check.blocking_reasons)


def test_memo_only_claims_cannot_be_submitted() -> None:
    """Company-paid flights alone are not a claim; there is nothing to reimburse."""
    assert not check_can_submit([_outcome(ClaimLineStatus.MEMO)]).can_submit


# ------------------------------------------------------------------ transitions


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ClaimStatus.DRAFT, ClaimStatus.PENDING_APPROVAL),
        (ClaimStatus.PENDING_APPROVAL, ClaimStatus.PENDING_FINANCE),
        (ClaimStatus.PENDING_APPROVAL, ClaimStatus.DRAFT),
        (ClaimStatus.PENDING_FINANCE, ClaimStatus.VERIFIED),
        (ClaimStatus.VERIFIED, ClaimStatus.SCHEDULED_FOR_PAYMENT),
        (ClaimStatus.SCHEDULED_FOR_PAYMENT, ClaimStatus.PAID),
    ],
)
def test_the_normal_path_is_permitted(current: ClaimStatus, target: ClaimStatus) -> None:
    assert_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        # Skipping approvals entirely.
        (ClaimStatus.DRAFT, ClaimStatus.VERIFIED),
        (ClaimStatus.DRAFT, ClaimStatus.PAID),
        # Finance verification cannot be bypassed (§2.1).
        (ClaimStatus.PENDING_APPROVAL, ClaimStatus.VERIFIED),
        # Nothing follows a terminal state.
        (ClaimStatus.PAID, ClaimStatus.DRAFT),
        (ClaimStatus.REJECTED, ClaimStatus.PENDING_APPROVAL),
    ],
)
def test_shortcuts_and_reopenings_are_refused(current: ClaimStatus, target: ClaimStatus) -> None:
    with pytest.raises(TransitionError):
        assert_transition(current, target)


def test_a_returned_claim_goes_back_to_draft() -> None:
    """§2.3: back to the employee for correction, against the same Travel Request ID."""
    assert_transition(ClaimStatus.PENDING_APPROVAL, ClaimStatus.DRAFT)
    assert_transition(ClaimStatus.PENDING_FINANCE, ClaimStatus.DRAFT)


# -------------------------------------------------------------------- deadlines


def test_the_submission_deadline_is_seven_calendar_days_after_return() -> None:
    """The sample trip returns 20 Jun, so the claim is due by 27 Jun."""
    assert submission_deadline(date(2026, 6, 20)) == date(2026, 6, 27)


def test_a_claim_submitted_on_the_deadline_is_not_overdue() -> None:
    assert not is_overdue(
        return_date=date(2026, 6, 20),
        submitted_at=date(2026, 6, 27),
        today=date(2026, 6, 27),
    )


def test_a_claim_submitted_the_day_after_is_overdue() -> None:
    assert is_overdue(
        return_date=date(2026, 6, 20),
        submitted_at=date(2026, 6, 28),
        today=date(2026, 6, 28),
    )


def test_an_unsubmitted_claim_goes_overdue_on_its_own() -> None:
    """Nothing has been submitted, and the deadline has still passed."""
    assert is_overdue(return_date=date(2026, 6, 20), submitted_at=None, today=date(2026, 7, 1))


# ----------------------------------------------------------------- payment runs


@pytest.mark.parametrize(
    ("verified", "expected"),
    [
        (date(2026, 6, 21), date(2026, 6, 25)),
        (date(2026, 6, 26), date(2026, 7, 10)),
        (date(2026, 6, 1), date(2026, 6, 10)),
        (date(2026, 6, 11), date(2026, 6, 25)),
        # On a run day, the claim makes that day's run.
        (date(2026, 6, 10), date(2026, 6, 10)),
        (date(2026, 6, 25), date(2026, 6, 25)),
        # Year boundary.
        (date(2026, 12, 26), date(2027, 1, 10)),
    ],
)
def test_the_next_run_is_the_tenth_or_the_twenty_fifth(verified: date, expected: date) -> None:
    assert next_payment_run(verified) == expected


def test_run_days_come_from_policy_not_from_code() -> None:
    assert next_payment_run(date(2026, 6, 3), run_days=[5, 20]) == date(2026, 6, 5)


# --------------------------------------------------------------------- advance


def test_the_sample_advance_exceeds_the_employee_borne_ceiling() -> None:
    """20,000 drawn against a 10,000 employee-borne estimate. 60% of that is 6,000.

    A warning, not a block: it is over because the request put lodging on the company and the
    employee ended up paying it.
    """
    check = check_advance_against_estimate(
        advance=Decimal("20000.00"),
        employee_borne_estimate=Decimal("10000.00"),
        max_fraction=0.60,
    )

    assert not check.within_policy
    assert "6000.00" in check.message
    assert "§1.2" in check.message


def test_an_advance_within_sixty_percent_passes() -> None:
    check = check_advance_against_estimate(
        advance=Decimal("6000.00"),
        employee_borne_estimate=Decimal("10000.00"),
        max_fraction=0.60,
    )

    assert check.within_policy


def test_a_zero_estimate_cannot_be_checked() -> None:
    check = check_advance_against_estimate(
        advance=Decimal("1000.00"), employee_borne_estimate=Decimal("0.00"), max_fraction=0.60
    )

    assert not check.within_policy
    assert "cannot be checked" in check.message
