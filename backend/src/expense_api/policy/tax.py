"""Split a bill-level tax across the lines it was charged on.

A hotel folio states one GST figure for the whole subtotal, and that subtotal includes items
policy will not reimburse. Reimbursing the tax on a mini bar is the same mistake as reimbursing
the mini bar, so the tax has to be attributed line by line before anything is disallowed.

For the sample folio the split is exact: 17,250/19,200 x 2,304 = 2,070.00, and laundry and
mini bar carry 54.00 and 45.60 between them - the 99.60 that, with their 830.00 of charges,
makes the claim's 929.60 disallowed total.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

_PAISE = Decimal("0.01")
_ZERO = Decimal("0.00")


def apportion_tax(line_amounts: Sequence[Decimal], total_tax: Decimal) -> list[Decimal]:
    """Pro-rata on each line's share of the pre-tax subtotal.

    The returned shares always sum to `total_tax` exactly. Rounding each share independently
    would leave a residue, and a claim that misses its own stated tax by a paisa is a claim
    Finance has to query.
    """
    if not line_amounts:
        return []

    subtotal = sum(line_amounts, _ZERO)
    if subtotal == _ZERO:
        raise ValueError("Cannot apportion tax across lines with a zero subtotal")

    if total_tax == _ZERO:
        return [_ZERO for _ in line_amounts]

    shares = [
        (amount / subtotal * total_tax).quantize(_PAISE, rounding=ROUND_HALF_UP)
        for amount in line_amounts
    ]

    # Put the residue on the largest line: it is the one whose proportion is least distorted by
    # absorbing it, and it keeps the total exact.
    residue = total_tax - sum(shares, _ZERO)
    if residue != _ZERO:
        largest = max(range(len(line_amounts)), key=lambda i: line_amounts[i])
        shares[largest] += residue

    return shares
