"""Unit 4: the reconciliation guard.

The single most important test in this unit is the one where OCR silently loses a folio line.
Everything else here is scaffolding around it.
"""

from decimal import Decimal

from expense_api.evidence.reconcile import ReconciliationStatus, reconcile


def test_balanced_when_lines_sum_to_the_stated_subtotal() -> None:
    result = reconcile(
        line_amounts=[Decimal("5750.00"), Decimal("5750.00"), Decimal("450.00")],
        stated_subtotal=Decimal("11950.00"),
    )

    assert result.status is ReconciliationStatus.BALANCED
    assert result.difference == Decimal("0.00")
    assert result.is_usable


def test_the_full_hotel_folio_balances() -> None:
    """Six lines, 19,200.00 stated. This is what a correct extraction looks like."""
    result = reconcile(
        line_amounts=[
            Decimal("5750.00"),
            Decimal("5750.00"),
            Decimal("450.00"),
            Decimal("5750.00"),
            Decimal("380.00"),
            Decimal("1120.00"),
        ],
        stated_subtotal=Decimal("19200.00"),
    )

    assert result.status is ReconciliationStatus.BALANCED


def test_catches_the_room_charge_ocr_drops() -> None:
    """Trap 13, and the reason this module exists.

    Both receipt images have a fold drawn across them. On hotel_invoice_1188.png the fold sits
    on the second room charge: the label becomes "Spodun-Reom-Cheange." and the amount degrades
    to "5.750.00". If a parser then skips the unreadable line, five lines sum to 13,450 against
    a stated 19,200 - a claim understated by 3,750, reported as a success.
    """
    result = reconcile(
        line_amounts=[
            Decimal("5750.00"),
            Decimal("450.00"),
            Decimal("5750.00"),
            Decimal("380.00"),
            Decimal("1120.00"),
        ],
        stated_subtotal=Decimal("19200.00"),
    )

    assert result.status is ReconciliationStatus.MISMATCH
    assert result.extracted_total == Decimal("13450.00")
    assert result.difference == Decimal("-5750.00")
    assert not result.is_usable
    # The message has to name the shortfall; "reconciliation failed" tells a human nothing.
    assert "5750.00" in result.message
    assert "19200.00" in result.message


def test_catches_an_overstatement_too() -> None:
    """A line counted twice is as wrong as a line missed, and less obvious."""
    result = reconcile(
        line_amounts=[Decimal("5750.00"), Decimal("5750.00"), Decimal("5750.00")],
        stated_subtotal=Decimal("11500.00"),
    )

    assert result.status is ReconciliationStatus.MISMATCH
    assert result.difference == Decimal("5750.00")


def test_a_bill_with_no_stated_subtotal_is_unverifiable_not_balanced() -> None:
    """Most cab receipts state only a total. Absence of a check is not a passed check."""
    result = reconcile(line_amounts=[Decimal("172.00")], stated_subtotal=None)

    assert result.status is ReconciliationStatus.UNVERIFIABLE
    # Usable, because there is nothing to contradict - but it must not read as verified.
    assert result.is_usable
    assert result.difference is None


def test_no_lines_at_all_is_a_mismatch_when_a_subtotal_was_stated() -> None:
    """Extracting nothing from a bill that states 19,200 is the loudest possible failure."""
    result = reconcile(line_amounts=[], stated_subtotal=Decimal("19200.00"))

    assert result.status is ReconciliationStatus.MISMATCH
    assert result.extracted_total == Decimal("0.00")


def test_tolerance_absorbs_a_rounding_paisa_but_not_a_missing_line() -> None:
    """Real bills round. A one-paisa gap is noise; anything larger is a human's problem."""
    near = reconcile(
        line_amounts=[Decimal("100.00"), Decimal("50.01")],
        stated_subtotal=Decimal("150.00"),
        tolerance=Decimal("0.01"),
    )
    assert near.status is ReconciliationStatus.BALANCED

    far = reconcile(
        line_amounts=[Decimal("100.00"), Decimal("50.10")],
        stated_subtotal=Decimal("150.00"),
        tolerance=Decimal("0.01"),
    )
    assert far.status is ReconciliationStatus.MISMATCH


def test_default_tolerance_is_exact() -> None:
    """Money is stored as integer paise, so exactness is the honest default."""
    result = reconcile(
        line_amounts=[Decimal("100.00"), Decimal("50.01")],
        stated_subtotal=Decimal("150.00"),
    )

    assert result.status is ReconciliationStatus.MISMATCH


def test_the_dinner_bill_balances_including_service_charge() -> None:
    """2050.00 + CGST 51.25 + SGST 51.25 + service charge 102.50 = 2255.00."""
    result = reconcile(
        line_amounts=[
            Decimal("2050.00"),
            Decimal("51.25"),
            Decimal("51.25"),
            Decimal("102.50"),
        ],
        stated_subtotal=Decimal("2255.00"),
    )

    assert result.status is ReconciliationStatus.BALANCED
