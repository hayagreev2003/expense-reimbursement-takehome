"""Mail from vendors nobody wrote a parser for - the case a demo pack cannot cover.

Every rule in `classify` and every parser in `rule_based` was written against the fifteen
messages in `pack/`. That is the right way to build them and the wrong place to stop: the first
real `.eml` an employee forwards comes from a sender with different wording, and the failure
mode was silent - the document was classified `unknown`, set aside as "not a claimable
document", and its figure never appeared anywhere.

These tests are the floor under that. A receipt with a labelled total becomes a claim line with
an amount; a document without one becomes needs-input, which is visible and blocks submission;
and neither path is allowed to paper over a reconciliation failure.
"""

from datetime import datetime
from decimal import Decimal
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from expense_api.config.settings import settings
from expense_api.db.models import DocKind, ExtractionStatus
from expense_api.evidence.classify import classify, produces_claim_lines
from expense_api.evidence.extractors.base import ExtractionResult
from expense_api.evidence.extractors.rule_based import RuleBasedExtractor
from expense_api.evidence.ingest import parse_eml
from expense_api.evidence.reconcile import ReconciliationStatus

CLAIMANT_EMAIL = "chaitanya.reddy@nortexindustries.com"
CLAIMANT_NAME = "Chaitanya Reddy"


def _mail(
    tmp_path: Path,
    *,
    sender: str,
    subject: str,
    body: str,
    name: str = "forwarded.eml",
    to: str = CLAIMANT_EMAIL,
) -> Path:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = format_datetime(datetime(2026, 6, 18, 21, 30))
    message["Message-ID"] = f"<{name}@vendor.example>"
    message.set_content(body)
    path = tmp_path / name
    path.write_bytes(bytes(message.as_bytes()))
    return path


def _read(path: Path) -> tuple[DocKind, ExtractionResult]:
    parsed = parse_eml(path, receipts_dir=path.parent)
    kind = classify(parsed, claimant_email=CLAIMANT_EMAIL, claimant_name=CLAIMANT_NAME)
    return kind, RuleBasedExtractor().extract(parsed, kind)


# ------------------------------------------------------------------ classification


def test_a_cab_receipt_from_an_unseen_vendor_is_claimable(tmp_path: Path) -> None:
    """No "Thanks for riding" anywhere in it. It is still a cab fare."""
    kind, result = _read(
        _mail(
            tmp_path,
            sender="Ola Cabs <receipts@olacabs.com>",
            subject="Your ride receipt",
            body="Ride on 18 Jun 2026, Andheri to BKC.\nTotal INR 480.00\nPayment: UPI\n",
        )
    )

    assert kind is DocKind.CAB_RECEIPT
    assert produces_claim_lines(kind)
    assert result.status is ExtractionStatus.EXTRACTED
    assert result.items[0].gross_amount == Decimal("480.00")
    assert result.items[0].merchant == "Ola"
    assert result.items[0].txn_date is not None


def test_a_hotel_invoice_from_an_unseen_hotel_is_claimable(tmp_path: Path) -> None:
    kind, result = _read(
        _mail(
            tmp_path,
            sender="Sunrise Residency <billing@sunriseresidency.example>",
            subject="Invoice no SR/4471 for your stay",
            body=(
                "Guest: Chaitanya Reddy\nCheck-in 16 Jun 2026\nNights 4\n"
                "Sub total  18,000.00\nCGST 9%  1,620.00\nSGST 9%  1,620.00\n"
                "Grand total  21,240.00\nSettled by: Personal Card\n"
            ),
            name="hotel.eml",
        )
    )

    assert kind is DocKind.HOTEL_INVOICE
    assert result.status is ExtractionStatus.EXTRACTED
    item = result.items[0]
    assert item.gross_amount == Decimal("21240.00")
    # The §3.1 lodging limit is per night, so a lodging line without a divisor is unassessable.
    assert item.nights == 4
    assert item.tax_amount == Decimal("3240.00")
    # Components the bill printed, checked against the total it claims.
    assert result.reconciliation is not None
    assert result.reconciliation.status is ReconciliationStatus.BALANCED


def test_a_booking_confirmation_is_not_treated_as_the_invoice(tmp_path: Path) -> None:
    """The tax invoice is the claimable document; a voucher is not (§3.1)."""
    kind, _ = _read(
        _mail(
            tmp_path,
            sender="Stays <noreply@somestays.example>",
            subject="Booking confirmed - Sunrise Residency, 16-20 Jun",
            body="Your stay is confirmed.\nRoom tariff INR 4,500.00 per night\nNights 4\n",
            name="voucher.eml",
        )
    )

    assert kind is DocKind.HOTEL_VOUCHER
    assert not produces_claim_lines(kind)


def test_an_unseen_vendors_sale_mail_is_still_noise(tmp_path: Path) -> None:
    """A promotion names hotels and amounts, and must not read as a hotel invoice."""
    kind, _ = _read(
        _mail(
            tmp_path,
            sender="Deals <hello@traveldeals.example>",
            subject="Flat 2,000 off your next hotel stay",
            body="Monsoon sale is live. Use code MONSOON. Unsubscribe here.\n",
            name="promo.eml",
        )
    )

    assert kind is DocKind.PROMOTIONAL


def test_a_payment_failure_from_an_unseen_cab_vendor_is_not_a_receipt(tmp_path: Path) -> None:
    kind, _ = _read(
        _mail(
            tmp_path,
            sender="Rapido <alerts@rapido.example>",
            subject="Payment failed for your trip",
            body="We could not charge your card for your ride. Amount due INR 260.00\n",
            name="failed.eml",
        )
    )

    assert kind is DocKind.CAB_PAYMENT_FAILURE
    assert not produces_claim_lines(kind)


def test_a_colleagues_internal_mail_never_becomes_a_claim_line_by_keyword(tmp_path: Path) -> None:
    """Generic matching must not turn an internal thread that mentions money into an expense."""
    kind, _ = _read(
        _mail(
            tmp_path,
            sender="Deepa Nair <deepa.nair@nortexindustries.com>",
            subject="Re: cab arrangements",
            body="The airport cab will be about INR 1,200.00 each way. Fine by me.\n",
            name="internal.eml",
        )
    )

    assert kind is DocKind.UNKNOWN
    assert not produces_claim_lines(kind)


# -------------------------------------------------------------------- extraction


def test_a_receipt_with_no_labelled_total_needs_a_human(tmp_path: Path) -> None:
    """Never a guessed figure. An unlabelled number is a table number as often as money."""
    _, result = _read(
        _mail(
            tmp_path,
            sender="Ola Cabs <receipts@olacabs.com>",
            subject="Your ride receipt",
            body="Thanks for travelling with us. Ride on 18 Jun 2026. 4 stops, 12 km.\n",
            name="no_total.eml",
        )
    )

    assert result.status is ExtractionStatus.NEEDS_INPUT
    assert result.items == []
    assert result.needs_input_reason


def test_a_bare_total_is_recorded_as_unverifiable_not_reconciled(tmp_path: Path) -> None:
    """A total checked against itself always balances and proves nothing."""
    _, result = _read(
        _mail(
            tmp_path,
            sender="Ola Cabs <receipts@olacabs.com>",
            subject="Your ride receipt",
            body="Ride on 18 Jun 2026.\nTotal INR 480.00\n",
            name="bare.eml",
        )
    )

    assert result.status is ExtractionStatus.EXTRACTED
    assert result.reconciliation is not None
    assert result.reconciliation.status is ReconciliationStatus.UNVERIFIABLE


def test_the_generic_reader_never_replaces_a_failed_reconciliation(tmp_path: Path) -> None:
    """The one thing the fallback must not do.

    The pack's hotel folio itemises five charges against a stated subtotal. If a parser reads
    them and the sum does not match, that discrepancy is the finding - a whole-bill total that
    balances against itself would bury exactly what reconcile.py exists to surface.
    """
    kind, result = _read(
        _mail(
            tmp_path,
            sender="Keys Prime Whitefield <billing@keysprime.example>",
            subject="Tax Invoice KPW/26-27/9999 - Chaitanya Reddy",
            body=(
                "Folio no KPW/26-27/9999\nCheck-in 16 Jun 2026\nNights 4\n"
                "Room charges   17,250.00\nLaundry   450.00\n"
                "Sub total   19,200.00\nInvoice total   21,504.00\n"
            ),
            name="mismatch.eml",
        )
    )

    assert kind is DocKind.HOTEL_INVOICE
    assert result.status is ExtractionStatus.NEEDS_INPUT
    assert result.reconciliation is not None
    assert result.reconciliation.status is ReconciliationStatus.MISMATCH
    # The lines it did read are carried along for whoever fixes it, not discarded.
    assert len(result.items) == 2


def test_the_packs_own_messages_still_take_the_specific_parsers(tmp_path: Path) -> None:
    """The fallback is a floor, not a replacement: the folio is still decomposed line by line."""
    parsed = parse_eml(
        settings.pack_dir / "sample_emails" / "12_hotel_invoice.eml",
        receipts_dir=settings.pack_dir / "receipts",
    )
    result = RuleBasedExtractor().extract(parsed, DocKind.HOTEL_INVOICE)

    assert result.status is ExtractionStatus.EXTRACTED
    assert len(result.items) == 4
    assert {item.description for item in result.items} == {
        "Room charges",
        "Laundry",
        "Mini bar",
        "In-room dining",
    }
