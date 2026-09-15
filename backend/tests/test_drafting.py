"""Unit 5: classifying and attributing lines before policy sees them."""

from datetime import date
from decimal import Decimal

import pytest

from expense_api.claims.drafting import (
    DraftContext,
    classify_head,
    draft_line,
    find_coverage_gaps,
)
from expense_api.db.models import ClaimLineStatus, DocKind, ExpenseHead, PaidBy
from expense_api.evidence.extractors.base import ExtractedItem

CONTEXT = DraftContext(
    claimant_name="Chaitanya Reddy",
    company_name="Nortex Industries Ltd",
    visiting_company="Vertex Technologies",
    note="Keeping this for the claim. Dinner with Vertex procurement team, 4 people.",
)


def _item(
    amount: str,
    description: str,
    *,
    payer: str | None = "Chaitanya",
    payment: str | None = "Personal - HDFC Credit Card ****2288",
    nights: int | None = None,
) -> ExtractedItem:
    return ExtractedItem(
        gross_amount=Decimal(amount),
        description=description,
        payer_name=payer,
        payment_method=payment,
        txn_date=date(2026, 6, 17),
        nights=nights,
    )


# ------------------------------------------------------------------------- heads


@pytest.mark.parametrize(
    ("kind", "description", "expected"),
    [
        (DocKind.CAB_RECEIPT, "Baner, Pune to PNQ", ExpenseHead.TRANSPORT),
        (DocKind.FLIGHT_BOOKING, "6E-6284 PNQ-BLR", ExpenseHead.TRANSPORT),
        (DocKind.HOTEL_INVOICE, "Room charges", ExpenseHead.LODGING),
        (DocKind.HOTEL_INVOICE, "Laundry", ExpenseHead.MISC),
        (DocKind.HOTEL_INVOICE, "Mini bar", ExpenseHead.MISC),
    ],
)
def test_heads_are_assigned_from_the_line(
    kind: DocKind, description: str, expected: ExpenseHead
) -> None:
    assert classify_head(kind, description) is expected


def test_in_room_dining_is_a_meal_not_a_folio_extra() -> None:
    """§4 lists laundry, mini bar, in-room entertainment, spa and gym. It does not list food.

    Filing this under MISC would see it disallowed with the mini bar and cost the employee
    1,120.00 they are entitled to.
    """
    assert classify_head(DocKind.HOTEL_INVOICE, "In-room dining") is ExpenseHead.MEALS


def test_a_hosted_meal_is_business_entertainment() -> None:
    """§3.5: a meal hosted for a customer is not meal allowance.

    The employee's own note names the customer the trip was to visit.
    """
    assert (
        classify_head(DocKind.RESTAURANT_BILL, "Dinner, 4 covers", context=CONTEXT)
        is ExpenseHead.BUSINESS_ENTERTAINMENT
    )


def test_an_unaccompanied_meal_stays_a_meal() -> None:
    solo = DraftContext(claimant_name="Chaitanya Reddy", note="Dinner at the hotel.")

    assert classify_head(DocKind.RESTAURANT_BILL, "Dinner", context=solo) is ExpenseHead.MEALS


def test_hosting_is_detected_from_generic_wording_too() -> None:
    """Not every note will name the customer from the travel request."""
    generic = DraftContext(
        claimant_name="Chaitanya Reddy", note="Dinner with the client procurement team."
    )

    assert (
        classify_head(DocKind.RESTAURANT_BILL, "Dinner", context=generic)
        is ExpenseHead.BUSINESS_ENTERTAINMENT
    )


# -------------------------------------------------------------------- attribution


def test_a_normal_employee_paid_line_is_allowed() -> None:
    line = draft_line(
        _item("172.00", "Vertex to hotel"), DocKind.CAB_RECEIPT, context=CONTEXT, source_index=0
    )

    assert line.status is ClaimLineStatus.ALLOWED
    assert line.paid_by is PaidBy.EMPLOYEE
    assert line.head is ExpenseHead.TRANSPORT


def test_a_company_paid_flight_becomes_a_memo_line() -> None:
    """§3.2: employees do not claim centrally booked air travel. Recorded, not reimbursed."""
    line = draft_line(
        _item(
            "5016.00",
            "6E-6284 PNQ-BLR",
            payer="MR CHAITANYA REDDY",
            payment="Corporate Card ending 4417 (Nortex Industries Ltd)",
        ),
        DocKind.FLIGHT_BOOKING,
        context=CONTEXT,
        source_index=0,
    )

    assert line.paid_by is PaidBy.COMPANY
    assert line.status is ClaimLineStatus.MEMO
    assert line.status_reason is not None
    assert "not reimbursed" in line.status_reason


def test_a_colleagues_cab_is_rejected_with_her_name() -> None:
    line = draft_line(
        _item("640.00", "Guindy to MAA", payer="Deepa", payment=None),
        DocKind.THIRD_PARTY_FORWARD,
        context=CONTEXT,
        source_index=0,
    )

    assert line.status is ClaimLineStatus.REJECTED
    assert line.status_reason is not None
    assert "Deepa" in line.status_reason


def test_the_hotel_is_employee_paid_even_though_it_was_budgeted_to_the_company() -> None:
    """The travel request plans Company; the invoice shows a personal card. Evidence wins."""
    line = draft_line(
        _item(
            "17250.00",
            "Room charges",
            payer="Chaitanya Reddy",
            payment="Guest, HDFC Credit Card ****2288",
            nights=3,
        ),
        DocKind.HOTEL_INVOICE,
        context=CONTEXT,
        source_index=0,
    )

    assert line.paid_by is PaidBy.EMPLOYEE
    assert line.status is ClaimLineStatus.ALLOWED
    assert line.head is ExpenseHead.LODGING
    assert line.nights == 3


# ----------------------------------------------------------------- coverage gaps


def test_the_unaccounted_night_is_flagged() -> None:
    """The sample trip runs 16-20 Jun; the folio covers three nights from the 16th.

    Nothing accounts for the night of the 19th, and the return flight is not until the evening
    of the 20th. Flagged, not filled.
    """
    gaps = find_coverage_gaps(
        trip_from=date(2026, 6, 16),
        trip_to=date(2026, 6, 20),
        stays=[(date(2026, 6, 16), 3)],
    )

    assert gaps == [date(2026, 6, 19)]


def test_two_stays_cover_the_trip_between_them() -> None:
    """A mailed folio plus a bill the employee forwards later. Both count."""
    gaps = find_coverage_gaps(
        trip_from=date(2026, 6, 16),
        trip_to=date(2026, 6, 20),
        stays=[(date(2026, 6, 16), 3), (date(2026, 6, 19), 1)],
    )

    assert gaps == []


def test_a_fully_covered_trip_has_no_gaps() -> None:
    gaps = find_coverage_gaps(
        trip_from=date(2026, 6, 16),
        trip_to=date(2026, 6, 20),
        stays=[(date(2026, 6, 16), 4)],
    )

    assert gaps == []


def test_no_lodging_at_all_flags_every_night() -> None:
    gaps = find_coverage_gaps(
        trip_from=date(2026, 6, 16),
        trip_to=date(2026, 6, 18),
        stays=[],
    )

    assert gaps == [date(2026, 6, 16), date(2026, 6, 17)]


def test_a_same_day_trip_needs_no_accommodation() -> None:
    gaps = find_coverage_gaps(
        trip_from=date(2026, 6, 16),
        trip_to=date(2026, 6, 16),
        stays=[],
    )

    assert gaps == []
