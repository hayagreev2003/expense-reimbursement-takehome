"""Unit 5: whose expense it is, and who actually paid."""

import pytest

from expense_api.claims.attribution import (
    Attribution,
    attribute,
    derive_paid_by,
)
from expense_api.db.models import PaidBy

CLAIMANT = "Chaitanya Reddy"


@pytest.mark.parametrize(
    "payer",
    [
        # The same person, as three different senders print them.
        "Chaitanya",
        "Chaitanya Reddy",
        "MR CHAITANYA REDDY",
        "chaitanya reddy",
        "Reddy, Chaitanya",
    ],
)
def test_the_claimants_own_receipts_are_attributed_to_them(payer: str) -> None:
    result = attribute(payer, claimant_name=CLAIMANT)

    assert result.attribution is Attribution.CLAIMANT
    assert not result.is_rejected


def test_a_colleagues_expense_is_rejected_and_the_reason_names_her() -> None:
    """Message 13. Who forwarded it and which trip it belongs to are both irrelevant."""
    result = attribute("Deepa", claimant_name=CLAIMANT)

    assert result.attribution is Attribution.THIRD_PARTY
    assert result.is_rejected
    assert "Deepa" in result.reason
    assert "§4" in result.reason


def test_an_unnamed_payer_is_not_a_rejection() -> None:
    """The dinner bill names nobody. Absence of a name is not evidence of someone else."""
    result = attribute(None, claimant_name=CLAIMANT)

    assert result.attribution is Attribution.UNKNOWN
    assert not result.is_rejected


def test_a_shared_surname_is_enough_to_match() -> None:
    """Receipts print inconsistent fragments of a name; requiring the whole string would
    reject the claimant's own hotel folio."""
    assert attribute("Reddy", claimant_name=CLAIMANT).attribution is Attribution.CLAIMANT


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        # The pack's actual payment strings.
        ("Corporate Card ending 4417 (Nortex Industries Ltd)", PaidBy.COMPANY),
        ("Personal - HDFC Credit Card ****2288", PaidBy.EMPLOYEE),
        ("Guest, HDFC Credit Card ****2288", PaidBy.EMPLOYEE),
        ("CARD ****2288", PaidBy.EMPLOYEE),
        (None, PaidBy.EMPLOYEE),
        ("", PaidBy.EMPLOYEE),
    ],
)
def test_paid_by_comes_from_the_payment_evidence(method: str | None, expected: PaidBy) -> None:
    assert derive_paid_by(method) is expected


def test_corporate_card_wins_over_the_word_card() -> None:
    """ "Corporate Card ending 4417" contains "card"; the company signal is checked first."""
    assert derive_paid_by("Corporate Card ending 4417") is PaidBy.COMPANY


def test_the_hotel_is_employee_paid_despite_being_budgeted_to_the_company() -> None:
    """The trap: the travel request says Company and the voucher says "Pay at Hotel".

    The invoice says the guest settled it on a personal card, and the invoice is the evidence.
    The settlement summary's SUMIF keys on this word, so getting it from the plan would drop
    20,574.40 out of the reimbursable total.
    """
    assert derive_paid_by("Guest, HDFC Credit Card ****2288") is PaidBy.EMPLOYEE


def test_the_company_name_marks_a_line_as_company_paid() -> None:
    assert (
        derive_paid_by("Billed to Nortex Industries Ltd", company_name="Nortex Industries Ltd")
        is PaidBy.COMPANY
    )
