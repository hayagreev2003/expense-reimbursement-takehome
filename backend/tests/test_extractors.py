"""Unit 4: extraction, checked against a fixture written from the source documents.

The fixture in tests/fixtures/expected_extraction.json was written by hand from pack/ before
any parser existed. Written afterwards it would only record whatever the parsers happened to
produce.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from expense_api.config.settings import settings
from expense_api.db.models import DocKind, ExtractionStatus
from expense_api.evidence.classify import classify
from expense_api.evidence.extractors.ocr import ocr_available, ocr_image
from expense_api.evidence.extractors.rule_based import RuleBasedExtractor
from expense_api.evidence.ingest import parse_eml
from expense_api.evidence.reconcile import ReconciliationStatus

EMAILS_DIR = settings.pack_dir / "sample_emails"
RECEIPTS_DIR = settings.pack_dir / "receipts"
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "expected_extraction.json").read_text())
EXPECTED = {k: v for k, v in FIXTURE.items() if not k.startswith("_")}

CLAIMANT_EMAIL = "chaitanya.reddy@nortexindustries.com"
CLAIMANT_NAME = "Chaitanya Reddy"

needs_ocr = pytest.mark.skipif(not ocr_available(), reason="tesseract is not installed")


def _extract(filename: str):  # type: ignore[no-untyped-def]
    parsed = parse_eml(EMAILS_DIR / filename, receipts_dir=RECEIPTS_DIR)
    kind = classify(parsed, claimant_email=CLAIMANT_EMAIL, claimant_name=CLAIMANT_NAME)
    return RuleBasedExtractor().extract(parsed, kind), kind


@pytest.mark.parametrize("filename", sorted(EXPECTED))
def test_extraction_matches_the_golden_fixture(filename: str) -> None:
    expected = EXPECTED[filename]
    if expected["doc_kind"] in {"restaurant_bill"} and not ocr_available():
        pytest.skip("tesseract is not installed")

    result, kind = _extract(filename)

    assert kind.value == expected["doc_kind"]
    assert result.status is ExtractionStatus.EXTRACTED, result.needs_input_reason
    assert len(result.items) == len(expected["line_items"])

    for actual, want in zip(result.items, expected["line_items"], strict=True):
        assert actual.gross_amount == Decimal(want["gross_amount"]), want["description"]
        assert actual.description == want["description"]
        assert actual.merchant == want["merchant"]
        assert actual.txn_date == (
            date.fromisoformat(want["txn_date"]) if want["txn_date"] else None
        )
        assert actual.tax_amount == (Decimal(want["tax_amount"]) if want["tax_amount"] else None)
        assert actual.payment_method == want["payment_method"]
        assert actual.payer_name == want["payer_name"]
        assert actual.bill_no == want["bill_no"]
        assert actual.nights == want.get("nights")


def test_both_flight_sectors_are_captured() -> None:
    """10,556.00 across two sectors, both on the corporate card (§3.2 memo, not a claim)."""
    result, _ = _extract("04_flight_eticket.eml")

    assert result.extracted_total == Decimal("10556.00")
    assert all("Corporate Card" in (i.payment_method or "") for i in result.items)


def test_the_hotel_folio_is_decomposed_not_totalled() -> None:
    """Not one 21,504 expense. Policy treats each of these lines differently."""
    result, _ = _extract("12_hotel_invoice.eml")

    by_label = {item.description: item.gross_amount for item in result.items}
    assert by_label == {
        "Room charges": Decimal("17250.00"),
        "Laundry": Decimal("450.00"),
        "Mini bar": Decimal("380.00"),
        "In-room dining": Decimal("1120.00"),
    }
    assert result.stated_subtotal == Decimal("19200.00")
    assert result.reconciliation is not None
    assert result.reconciliation.status is ReconciliationStatus.BALANCED


def test_room_charges_carry_the_night_count() -> None:
    """The §3.1 limit is per night, so the check needs a divisor: 17,250 / 3 = 5,750."""
    result, _ = _extract("12_hotel_invoice.eml")

    room = next(i for i in result.items if i.description == "Room charges")
    assert room.nights == 3
    assert room.gross_amount / room.nights == Decimal("5750")


def test_a_ride_receipts_components_are_checked_against_its_total() -> None:
    """1,229.00 + 96.00 + 90.02 = 1,415.02. A stated total checked against itself proves
    nothing, so where the parts are given they are what gets reconciled."""
    result, _ = _extract("06_uber_receipt_1.eml")

    assert result.reconciliation is not None
    assert result.reconciliation.status is ReconciliationStatus.BALANCED
    assert result.items[0].tax_amount == Decimal("90.02")


def test_a_receipt_with_only_a_total_is_unverifiable_not_verified() -> None:
    result, _ = _extract("09_uber_receipt_3.eml")

    assert result.reconciliation is not None
    assert result.reconciliation.status is ReconciliationStatus.UNVERIFIABLE
    assert result.is_usable


def test_the_colleagues_cab_is_extracted_so_the_rejection_can_name_a_figure() -> None:
    """Rejecting it silently would satisfy §4 and tell the employee nothing."""
    result, kind = _extract("13_colleague_forward.eml")

    assert kind is DocKind.THIRD_PARTY_FORWARD
    assert result.items[0].gross_amount == Decimal("640.00")
    assert result.items[0].payer_name == "Deepa"
    assert result.items[0].txn_date == date(2026, 5, 12)


def test_the_resend_extracts_identically_to_the_original() -> None:
    """Dedup needs them identical to collapse them; it is not classification's job to hide one."""
    original, _ = _extract("09_uber_receipt_3.eml")
    resend, _ = _extract("10_uber_receipt_3_resend.eml")

    assert original.items[0].gross_amount == resend.items[0].gross_amount
    assert original.items[0].txn_datetime == resend.items[0].txn_datetime
    assert original.items[0].description == resend.items[0].description


# --------------------------------------------------------------------------- OCR


@needs_ocr
def test_the_dinner_bill_is_read_from_its_image() -> None:
    """The body is the employee's note to themselves; the amounts are only in the photograph."""
    result, _ = _extract("11_dinner_bill.eml")

    item = result.items[0]
    assert item.gross_amount == Decimal("2255.00")
    assert item.bill_no == "4471"
    assert item.merchant == "Spice Terrace"
    assert item.txn_date == date(2026, 6, 18)
    assert item.tax_amount == Decimal("102.50")
    # OCR splits masked card digits as "****2 288"; storing the split would break matching.
    assert item.payment_method == "CARD ****2288"
    assert item.confidence < 1.0


@needs_ocr
def test_bill_number_4471_is_not_mistaken_for_the_employee_code() -> None:
    """The pack sets this trap deliberately: the dinner bill's number is the claimant's code."""
    result, _ = _extract("11_dinner_bill.eml")

    assert result.items[0].bill_no == "4471"
    assert result.items[0].merchant == "Spice Terrace"


@needs_ocr
def test_ocr_of_the_folio_loses_a_room_charge() -> None:
    """Trap 13, demonstrated rather than described.

    The fold drawn across hotel_invoice_1188.png sits on the second room charge. This asserts
    the damage is real, so the reconciliation guard is not defending against a hypothetical.
    """
    text = ocr_image(RECEIPTS_DIR / "hotel_invoice_1188.png")

    # The stated subtotal survives - which is exactly why it can be used as the check.
    assert "19,200.00" in text
    # Three room charges are printed; OCR recovers only two intact.
    assert text.count("Room Charge") == 2
    # The damaged line reads as a mangled label and a degraded amount.
    assert "5.750.00" in text


@needs_ocr
def test_extracting_the_folio_from_the_image_alone_is_caught_by_the_guard() -> None:
    """The failure the guard exists for: five lines, 13,450, against a stated 19,200.

    A pipeline without this check produces a claim understated by 3,750 and reports success.
    """
    from expense_api.evidence.reconcile import reconcile

    text = ocr_image(RECEIPTS_DIR / "hotel_invoice_1188.png")
    legible = [
        Decimal("5750.00"),  # 16-Jun Room Charge
        Decimal("450.00"),  # 17-Jun Laundry
        Decimal("5750.00"),  # 18-Jun Room Charge
        Decimal("380.00"),  # 18-Jun Mini Bar
        Decimal("1120.00"),  # 18-Jun In Room Dining
    ]
    assert "Spodun" in text or text.count("Room Charge") < 3

    result = reconcile(line_amounts=legible, stated_subtotal=Decimal("19200.00"))

    assert result.status is ReconciliationStatus.MISMATCH
    assert result.difference == Decimal("-5750.00")
    assert not result.is_usable


def test_an_unparseable_document_needs_input_rather_than_returning_nothing() -> None:
    """Silence is the failure mode this whole unit is built to avoid."""
    parsed = parse_eml(EMAILS_DIR / "02_travel_approval_granted.eml", receipts_dir=RECEIPTS_DIR)

    result = RuleBasedExtractor().extract(parsed, DocKind.APPROVAL_GRANT)

    assert result.status is ExtractionStatus.NEEDS_INPUT
    assert result.needs_input_reason
    assert not result.is_usable
