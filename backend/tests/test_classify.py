"""Unit 3: classification, which runs before extraction and decides what never reaches it.

Pure functions over parsed mail - no database. These are the mocked half.
"""

from pathlib import Path

import pytest

from expense_api.config.settings import settings
from expense_api.db.models import DocKind
from expense_api.evidence.classify import classify
from expense_api.evidence.ingest import parse_eml

EMAILS_DIR = settings.pack_dir / "sample_emails"
RECEIPTS_DIR = settings.pack_dir / "receipts"

CLAIMANT_EMAIL = "chaitanya.reddy@nortexindustries.com"
CLAIMANT_NAME = "Chaitanya Reddy"


def _classify(filename: str) -> DocKind:
    parsed = parse_eml(EMAILS_DIR / filename, receipts_dir=RECEIPTS_DIR)
    return classify(parsed, claimant_email=CLAIMANT_EMAIL, claimant_name=CLAIMANT_NAME)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("01_travel_approval_request.eml", DocKind.APPROVAL_REQUEST),
        ("02_travel_approval_granted.eml", DocKind.APPROVAL_GRANT),
        ("03_advance_disbursed.eml", DocKind.ADVANCE_NOTICE),
        ("04_flight_eticket.eml", DocKind.FLIGHT_BOOKING),
        ("05_hotel_voucher.eml", DocKind.HOTEL_VOUCHER),
        ("06_uber_receipt_1.eml", DocKind.CAB_RECEIPT),
        ("07_uber_receipt_2.eml", DocKind.CAB_RECEIPT),
        ("08_uber_payment_failed.eml", DocKind.CAB_PAYMENT_FAILURE),
        ("09_uber_receipt_3.eml", DocKind.CAB_RECEIPT),
        ("10_uber_receipt_3_resend.eml", DocKind.CAB_RECEIPT),
        ("11_dinner_bill.eml", DocKind.RESTAURANT_BILL),
        ("12_hotel_invoice.eml", DocKind.HOTEL_INVOICE),
        ("13_colleague_forward.eml", DocKind.THIRD_PARTY_FORWARD),
        ("14_promo_noise.eml", DocKind.PROMOTIONAL),
        ("15_return_cab.eml", DocKind.CAB_RECEIPT),
    ],
)
def test_every_message_in_the_pack_classifies_correctly(filename: str, expected: DocKind) -> None:
    assert _classify(filename) is expected


def test_payment_failure_is_not_a_receipt() -> None:
    """Message 08 carries a merchant, a date and an amount and is still not a receipt.

    It says "We could not charge your card" and "Amount due". Treating it as a receipt would
    claim 172.00 a second time, on top of message 09 which is the actual successful charge.
    """
    assert _classify("08_uber_payment_failed.eml") is DocKind.CAB_PAYMENT_FAILURE


def test_promotional_mail_is_classified_as_noise() -> None:
    """Message 14 is a hotel discount offer from the same sender domain as a real booking."""
    assert _classify("14_promo_noise.eml") is DocKind.PROMOTIONAL


def test_a_vendor_forward_is_still_the_claimants_receipt() -> None:
    """Message 10 is a forward, but Uber sent it and the rider is the claimant.

    It must stay a cab receipt: suppressing it here as a "forward" would hide the duplicate
    rather than record it, and §5.3 wants the suppression visible.
    """
    parsed = parse_eml(EMAILS_DIR / "10_uber_receipt_3_resend.eml", receipts_dir=RECEIPTS_DIR)

    assert parsed.subject is not None
    assert parsed.subject.lower().startswith("fwd:")
    assert classify(parsed, claimant_email=CLAIMANT_EMAIL, claimant_name=CLAIMANT_NAME) is (
        DocKind.CAB_RECEIPT
    )


def test_a_colleagues_forward_is_flagged_as_third_party() -> None:
    """Message 13 is also a forward, and the rider named in the body is Deepa, not Chaitanya.

    The sender being an internal colleague rather than the vendor is the signal. The rejection
    itself belongs to attribution in Unit 5; classification only has to route it there.
    """
    assert _classify("13_colleague_forward.eml") is DocKind.THIRD_PARTY_FORWARD


def test_classification_covers_the_whole_pack() -> None:
    """No message may fall through to UNKNOWN - an unclassified receipt is a lost claim line."""
    files = sorted(p for p in EMAILS_DIR.glob("*.eml"))

    assert len(files) == 15
    kinds = {
        path.name: classify(
            parse_eml(path, receipts_dir=RECEIPTS_DIR),
            claimant_email=CLAIMANT_EMAIL,
            claimant_name=CLAIMANT_NAME,
        )
        for path in files
    }

    unknown = [name for name, kind in kinds.items() if kind is DocKind.UNKNOWN]
    assert unknown == []


def test_kind_histogram_matches_the_pack() -> None:
    """Pins the shape of the inbox, so a classifier change cannot silently reshuffle it."""
    counts: dict[DocKind, int] = {}
    for path in sorted(EMAILS_DIR.glob("*.eml")):
        kind = classify(
            parse_eml(path, receipts_dir=RECEIPTS_DIR),
            claimant_email=CLAIMANT_EMAIL,
            claimant_name=CLAIMANT_NAME,
        )
        counts[kind] = counts.get(kind, 0) + 1

    assert counts == {
        DocKind.APPROVAL_REQUEST: 1,
        DocKind.APPROVAL_GRANT: 1,
        DocKind.ADVANCE_NOTICE: 1,
        DocKind.FLIGHT_BOOKING: 1,
        DocKind.HOTEL_VOUCHER: 1,
        DocKind.CAB_RECEIPT: 5,
        DocKind.CAB_PAYMENT_FAILURE: 1,
        DocKind.RESTAURANT_BILL: 1,
        DocKind.HOTEL_INVOICE: 1,
        DocKind.THIRD_PARTY_FORWARD: 1,
        DocKind.PROMOTIONAL: 1,
    }
    assert sum(counts.values()) == 15


def test_documents_that_never_reach_extraction() -> None:
    """Two kinds are terminal by policy, not by accident."""
    from expense_api.evidence.classify import produces_claim_lines

    assert not produces_claim_lines(DocKind.PROMOTIONAL)
    assert not produces_claim_lines(DocKind.CAB_PAYMENT_FAILURE)
    # Contextual documents inform the trip but are not expenses of the claimant.
    assert not produces_claim_lines(DocKind.APPROVAL_GRANT)
    assert not produces_claim_lines(DocKind.ADVANCE_NOTICE)
    assert not produces_claim_lines(DocKind.HOTEL_VOUCHER)

    assert produces_claim_lines(DocKind.CAB_RECEIPT)
    assert produces_claim_lines(DocKind.HOTEL_INVOICE)
    assert produces_claim_lines(DocKind.RESTAURANT_BILL)
    # The company-paid flights are memo rows, so they do reach extraction (§3.2).
    assert produces_claim_lines(DocKind.FLIGHT_BOOKING)


def test_unreadable_file_raises_rather_than_returning_empty(tmp_path: Path) -> None:
    """A parse failure must be loud. A silently empty document is a missing claim line."""
    from expense_api.evidence.ingest import EmailParseError

    broken = tmp_path / "broken.eml"
    broken.write_bytes(b"\xff\xfe not a message at all")

    with pytest.raises(EmailParseError):
        parse_eml(broken, receipts_dir=RECEIPTS_DIR)
