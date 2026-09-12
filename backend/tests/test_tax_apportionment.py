"""Unit 6: splitting a bill-level tax across the lines it sits on.

The hotel folio's 12% is charged on the whole subtotal, including items that are not
reimbursable. Reimbursing the tax on a mini bar is the same error as reimbursing the mini bar.
"""

from decimal import Decimal

import pytest

from expense_api.policy.tax import apportion_tax


def test_the_hotel_folio_splits_exactly() -> None:
    """CGST 1,152.00 + SGST 1,152.00 = 2,304.00 over a 19,200.00 subtotal.

    Every share divides cleanly here, which is what makes this a good anchor: any arithmetic
    error shows up as a figure that is simply wrong rather than a rounding argument.
    """
    shares = apportion_tax(
        [Decimal("17250.00"), Decimal("450.00"), Decimal("380.00"), Decimal("1120.00")],
        total_tax=Decimal("2304.00"),
    )

    assert shares == [
        Decimal("2070.00"),  # room charges
        Decimal("54.00"),  # laundry
        Decimal("45.60"),  # mini bar
        Decimal("134.40"),  # in-room dining
    ]
    assert sum(shares) == Decimal("2304.00")


def test_the_disallowed_share_is_the_figure_the_claim_turns_on() -> None:
    """Laundry 54.00 + mini bar 45.60 = 99.60, which with the 830.00 of charges makes 929.60."""
    shares = apportion_tax(
        [Decimal("17250.00"), Decimal("450.00"), Decimal("380.00"), Decimal("1120.00")],
        total_tax=Decimal("2304.00"),
    )

    assert shares[1] + shares[2] == Decimal("99.60")
    assert Decimal("830.00") + shares[1] + shares[2] == Decimal("929.60")


def test_shares_always_sum_to_the_stated_tax() -> None:
    """A residue left on the floor would make the claim stop reconciling by a paisa."""
    shares = apportion_tax(
        [Decimal("100.00"), Decimal("100.00"), Decimal("100.01")],
        total_tax=Decimal("10.00"),
    )

    assert sum(shares) == Decimal("10.00")


def test_the_rounding_residue_lands_on_the_largest_line() -> None:
    """Somewhere has to absorb it. The largest line distorts proportionally least."""
    shares = apportion_tax(
        [Decimal("1000.00"), Decimal("1.00"), Decimal("1.00")],
        total_tax=Decimal("1.00"),
    )

    assert sum(shares) == Decimal("1.00")
    assert shares[0] == max(shares)


def test_every_share_is_quantised_to_paise() -> None:
    shares = apportion_tax([Decimal("33.33"), Decimal("33.33"), Decimal("33.34")], Decimal("1.00"))

    assert all(share.as_tuple().exponent == -2 for share in shares)
    assert sum(shares) == Decimal("1.00")


def test_no_tax_produces_no_shares() -> None:
    shares = apportion_tax([Decimal("100.00"), Decimal("50.00")], total_tax=Decimal("0.00"))

    assert shares == [Decimal("0.00"), Decimal("0.00")]


def test_no_lines_is_an_empty_result_not_a_crash() -> None:
    assert apportion_tax([], total_tax=Decimal("100.00")) == []


def test_a_zero_subtotal_cannot_be_apportioned() -> None:
    """Dividing by nothing. Refuse rather than invent a split."""
    with pytest.raises(ValueError, match="zero"):
        apportion_tax([Decimal("0.00"), Decimal("0.00")], total_tax=Decimal("10.00"))


def test_a_single_line_takes_all_of_it() -> None:
    assert apportion_tax([Decimal("2050.00")], total_tax=Decimal("102.50")) == [Decimal("102.50")]
