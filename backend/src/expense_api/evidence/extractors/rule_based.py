"""Per-sender parsers, plus OCR for bills that arrive only as photographs.

This is the shipped, tested extraction path. It needs no credentials and behaves the same way
every run.

Its honest limitation, stated here because it belongs next to the code and not only in the
note: these parsers are tuned to the sender formats in this pack. An unseen vendor will not
parse. That is what the adapter seam is for - the answer is to swap the extractor, not to keep
adding regexes. The reconciliation guard sits underneath either adapter and catches the case
where a parser reads a bill partially and confidently.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal

from expense_api.db.models import DocKind
from expense_api.evidence.amounts import parse_amount
from expense_api.evidence.extractors.base import (
    ExtractedItem,
    ExtractionResult,
    from_items,
    needs_input,
)
from expense_api.evidence.extractors.ocr import OcrUnavailableError, ocr_image
from expense_api.evidence.ingest import ParsedEmail

logger = logging.getLogger(__name__)

NAME = "rule_based"

# "Tue, 16 Jun 2026 | 05:20 AM"  /  "Tue, 16 Jun 2026"
_RIDE_WHEN = re.compile(
    r"(?P<day>\d{1,2})\s+(?P<mon>[A-Za-z]{3})\s+(?P<year>\d{4})"
    r"(?:\s*\|\s*(?P<time>\d{1,2}:\d{2}\s*(?:AM|PM)?))?",
    re.I,
)
# "18-Jun-2026"
_DMY_DASHED = re.compile(r"(?P<day>\d{1,2})-(?P<mon>[A-Za-z]{3})-(?P<year>\d{4})")

_RIDER = re.compile(r"Thanks for riding,\s*(?P<name>[^\n,]+)", re.I)
_TOTAL_LINE = re.compile(r"^\s*Total\s+(?P<amount>.+?)\s*$", re.I | re.M)
_PAYMENT = re.compile(r"^\s*Payment:\s*(?P<method>.+?)\s*$", re.I | re.M)
_PICKUP = re.compile(r"^\s*Pickup\s+(?P<place>.+?)\s*$", re.I | re.M)
_DROP = re.compile(r"^\s*Drop\s+(?P<place>.+?)\s*$", re.I | re.M)
_COMPONENT = re.compile(
    r"^\s*(?P<label>Trip fare|Airport surcharge|Taxes)\s+(?P<amount>[\d.,]+)\s*$", re.I | re.M
)

_SECTOR_HEADER = re.compile(
    r"^(?P<from>[A-Za-z ]+?)\s*-\s*(?P<to>[A-Za-z ]+?)\s*\|.*?\|\s*"
    r"(?P<when>[A-Za-z]{3},\s*\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s*$",
    re.M,
)
_FLIGHT_NO = re.compile(r"^\s*\w[\w ]*?\s(?P<code>\d?[A-Z]{1,2}-?\d{2,4})\s+Dep.*$", re.M)
_AIRPORTS = re.compile(r"Dep\s+[\d:]+\s+(?P<from>[A-Z]{3})\s+Arr\s+[\d:]+\s+(?P<to>[A-Z]{3})")
_PASSENGER = re.compile(r"^\s*Passenger:\s*(?P<name>.+?)\s*$", re.I | re.M)
_BOOKING_REF = re.compile(r"\b(?P<ref>[A-Z]{2}\d{6,})\b")

_FOLIO_NO = re.compile(r"Folio no\s+(?P<ref>\S+)", re.I)
_NIGHTS = re.compile(r"Nights\s+(?P<n>\d+)", re.I)
_CHECK_IN = re.compile(r"Check-?in\s+(?P<when>\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", re.I)
_SETTLED_BY = re.compile(r"^\s*Settled by:\s*(?P<method>.+?)\s*$", re.I | re.M)
_FOLIO_LINE = re.compile(r"^\s*(?P<label>[A-Za-z][A-Za-z \-]+?)\s{2,}(?P<amount>[\d.,]+)\s*$", re.M)
_SUBTOTAL = re.compile(r"^\s*Sub ?total\s+(?P<amount>[\d.,]+)\s*$", re.I | re.M)
_GRAND_TOTAL = re.compile(
    r"^\s*(?:Invoice total|Grand total|TOTAL)\s+(?P<amount>[\d.,]+)", re.I | re.M
)

# Folio labels that are totals or taxes, not chargeable lines.
_NOT_A_CHARGE = {"sub total", "subtotal", "invoice total", "grand total", "total", "balance due"}
_TAX_LABEL = re.compile(r"^(c?gst|s?gst|igst|tax)", re.I)

# A printed receipt line: a label, then the amount at the end.
#
# The hotel body is column-aligned so _FOLIO_LINE's two-space rule works there. OCR of a
# photographed bill is not: "CGST 2.5% 51.25" has one space, and the label carries digits and a
# percent sign. Anchoring on the *trailing* amount is what makes "Service Charge 5% 102.50"
# read as 102.50 rather than as 5 - which is exactly the bug this replaced.
_OCR_CHARGE_LINE = re.compile(
    r"^[ \t]*(?P<label>\S.*?[A-Za-z].*?)[ \t]+(?P<amount>\d[\d.,]*)[ \t]*$", re.M
)
_SERVICE_CHARGE = re.compile(r"^service charge", re.I)

_BILL_NO = re.compile(r"Bill No\s+(?P<ref>\w+)", re.I)
_COVERS = re.compile(r"Covers\s+(?P<n>\d+)", re.I)
_PAID_BY_CARD = re.compile(r"Paid by\s+(?P<method>.+?)\s*$", re.I | re.M)
_MASKED_CARD = re.compile(r"(\*{2,})\s*(\d[\d ]*\d)")

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


class RuleBasedExtractor:
    """Dispatch on document kind. Each parser knows one sender's layout."""

    name = NAME

    def extract(self, parsed: ParsedEmail, kind: DocKind) -> ExtractionResult:
        match kind:
            case DocKind.CAB_RECEIPT | DocKind.THIRD_PARTY_FORWARD:
                return _extract_ride(parsed)
            case DocKind.FLIGHT_BOOKING:
                return _extract_flights(parsed)
            case DocKind.HOTEL_INVOICE:
                return _extract_hotel_invoice(parsed)
            case DocKind.RESTAURANT_BILL:
                return _extract_restaurant_bill(parsed)
            case _:
                return needs_input(NAME, f"No parser for document kind {kind.value!r}")


# ------------------------------------------------------------------------- rides


def _extract_ride(parsed: ParsedEmail) -> ExtractionResult:
    body = parsed.body_text

    total = _first_amount(_TOTAL_LINE, body)
    if total is None:
        return needs_input(NAME, "No total found on this ride receipt")

    when = _parse_when(body)
    rider = _group(_RIDER, body, "name")
    pickup = _group(_PICKUP, body, "place")
    drop = _group(_DROP, body, "place")

    components = [parse_amount(m.group("amount")) for m in _COMPONENT.finditer(body)]
    tax = next(
        (
            parse_amount(m.group("amount"))
            for m in _COMPONENT.finditer(body)
            if m.group("label").lower() == "taxes"
        ),
        None,
    )

    item = ExtractedItem(
        gross_amount=total,
        description=f"{pickup} to {drop}" if pickup and drop else (parsed.subject or "Cab"),
        merchant="Uber",
        txn_date=when.date() if when else None,
        txn_datetime=when,
        tax_amount=tax,
        payment_method=_group(_PAYMENT, body, "method"),
        payer_name=rider,
        raw_span=body[:400],
    )

    # Where the receipt itemises the fare, check the parts against the total it claims. Most
    # of these receipts give only a total, and that stays honestly unverifiable rather than
    # being reconciled against itself.
    reconcile_against = total if len([c for c in components if c]) >= 2 else None
    return from_items(
        NAME,
        [item],
        stated_subtotal=reconcile_against,
        stated_total=total,
        reconcile_amounts=[c for c in components if c] or None,
    )


# ----------------------------------------------------------------------- flights


def _extract_flights(parsed: ParsedEmail) -> ExtractionResult:
    body = parsed.body_text
    booking_ref = _group(_BOOKING_REF, parsed.subject or "", "ref")
    passenger = _group(_PASSENGER, body, "name")
    payment = _group(_PAYMENT, body, "method")

    headers = list(_SECTOR_HEADER.finditer(body))
    if not headers:
        return needs_input(NAME, "No flight sectors found on this e-ticket")

    items: list[ExtractedItem] = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(body)
        block = body[header.start() : end]

        total = _first_amount(_TOTAL_LINE, block)
        if total is None:
            continue

        flight_no = _group(_FLIGHT_NO, block, "code")
        airports = _AIRPORTS.search(block)
        route = (
            f"{airports.group('from')}-{airports.group('to')}"
            if airports
            else f"{header.group('from').strip()}-{header.group('to').strip()}"
        )
        taxes = re.search(r"Taxes\s*&\s*fees\s+(?P<amount>.+?)$", block, re.I | re.M)

        items.append(
            ExtractedItem(
                gross_amount=total,
                description=f"{flight_no} {route}" if flight_no else route,
                merchant="IndiGo" if "indigo" in block.lower() else "Air travel",
                txn_date=_parse_when(header.group("when")).date()  # type: ignore[union-attr]
                if _parse_when(header.group("when"))
                else None,
                tax_amount=parse_amount(taxes.group("amount")) if taxes else None,
                payment_method=_block_payment(block) or payment,
                payer_name=passenger,
                bill_no=booking_ref,
                raw_span=block[:400],
            )
        )

    if not items:
        return needs_input(NAME, "Flight sectors found but none carried a total")

    # The e-ticket states a total per sector and no grand total, so there is nothing
    # independent to reconcile against. Recorded as unverifiable rather than assumed correct.
    return from_items(
        NAME, items, stated_total=sum((i.gross_amount for i in items), Decimal("0.00"))
    )


def _block_payment(block: str) -> str | None:
    match = _PAYMENT.search(block)
    return match.group("method").strip() if match else None


# ------------------------------------------------------------------ hotel folio


def _extract_hotel_invoice(parsed: ParsedEmail) -> ExtractionResult:
    """Amounts come from the message body, which carries the folio as structured text.

    The attached image is OCR'd too, but as a cross-check and as something to show a human -
    not as the source of truth. On this pack's folio the fold across the image destroys a room
    charge, and preferring machine-readable text where it exists is simply the right ordering.
    """
    body = parsed.body_text
    ocr_text = _try_ocr(parsed)

    subtotal = _first_amount(_SUBTOTAL, body)
    grand_total = _first_amount(_GRAND_TOTAL, body)
    if subtotal is None:
        return needs_input(
            NAME,
            "No sub total on this invoice, so its line items cannot be checked",
            ocr_text=ocr_text,
        )

    bill_no = _group(_FOLIO_NO, body, "ref") or _group(_FOLIO_NO, parsed.subject or "", "ref")
    nights_match = _NIGHTS.search(body)
    nights = int(nights_match.group("n")) if nights_match else None
    check_in = _parse_when(_group(_CHECK_IN, body, "when") or "")
    guest = _guest_name(parsed)
    payment = _group(_SETTLED_BY, body, "method")

    items: list[ExtractedItem] = []
    for match in _FOLIO_LINE.finditer(body):
        label = match.group("label").strip()
        if label.lower() in _NOT_A_CHARGE or _TAX_LABEL.match(label):
            continue
        amount = parse_amount(match.group("amount"))
        if amount is None:
            continue
        items.append(
            ExtractedItem(
                gross_amount=amount,
                description=label,
                merchant=_hotel_name(parsed),
                txn_date=check_in.date() if check_in else None,
                payment_method=payment,
                payer_name=guest,
                bill_no=bill_no,
                # Only lodging needs a divisor for the §3.1 per-night limit.
                nights=nights if label.lower().startswith("room") else None,
                raw_span=match.group(0),
            )
        )

    return from_items(
        NAME, items, stated_subtotal=subtotal, stated_total=grand_total, ocr_text=ocr_text
    )


def _hotel_name(parsed: ParsedEmail) -> str | None:
    if parsed.sender_name:
        return parsed.sender_name
    if parsed.sender_email:
        return parsed.sender_email.split("@")[-1].split(".")[0].title()
    return None


def _guest_name(parsed: ParsedEmail) -> str | None:
    # "Tax Invoice KPW/26-27/1188 - Chaitanya Reddy"
    subject = parsed.subject or ""
    if " - " in subject:
        return subject.rsplit(" - ", 1)[-1].strip() or None
    return None


# -------------------------------------------------------------- restaurant bill


def _extract_restaurant_bill(parsed: ParsedEmail) -> ExtractionResult:
    """Image only. The body is the employee's note to themselves, not the bill."""
    ocr_text = _try_ocr(parsed)
    if not ocr_text:
        return needs_input(
            NAME, "This bill is an image and OCR is unavailable, so it needs manual entry"
        )

    total = _first_amount(_GRAND_TOTAL, ocr_text)
    if total is None:
        return needs_input(NAME, "Could not read a total from this bill image", ocr_text=ocr_text)

    subtotal = _first_amount(_SUBTOTAL, ocr_text)

    taxes: list[Decimal] = []
    service_charge: Decimal | None = None
    for match in _OCR_CHARGE_LINE.finditer(ocr_text):
        label = match.group("label").strip()
        amount = parse_amount(match.group("amount"))
        if amount is None:
            continue
        if _TAX_LABEL.match(label):
            taxes.append(amount)
        elif _SERVICE_CHARGE.match(label):
            service_charge = amount

    # Only GST is tax. A service charge is part of what was paid but is not a tax, and rolling
    # it in would misstate the tax that §3.1 apportionment later works from.
    tax_total = sum(taxes, Decimal("0.00")) or None

    when = _parse_when(ocr_text)
    covers = _COVERS.search(ocr_text)
    merchant = _first_nonempty_line(ocr_text)

    item = ExtractedItem(
        gross_amount=total,
        description=f"Dinner, {covers.group('n')} covers" if covers else "Restaurant bill",
        merchant=merchant.title() if merchant else None,
        txn_date=when.date() if when else None,
        txn_datetime=when,
        tax_amount=tax_total,
        payment_method=_normalise_card(_group(_PAID_BY_CARD, ocr_text, "method")),
        bill_no=_group(_BILL_NO, ocr_text, "ref"),
        # OCR, so never assert full confidence. The reconciliation below is the real check.
        confidence=0.8,
        raw_span=ocr_text[:400],
    )

    # One emitted line covering the whole bill, checked against the components the bill prints:
    # subtotal + GST + service charge should equal the printed total. That is a real check, and
    # it catches an OCR misread of any one of them.
    components: list[Decimal] | None = None
    if subtotal is not None:
        components = [subtotal, *taxes]
        if service_charge is not None:
            components.append(service_charge)

    return from_items(
        NAME,
        [item],
        stated_subtotal=total,
        stated_total=total,
        ocr_text=ocr_text,
        reconcile_amounts=components,
    )


def _normalise_card(value: str | None) -> str | None:
    """OCR splits masked card digits: "****2 288". Close the gap rather than store the split."""
    if not value:
        return None
    return _MASKED_CARD.sub(lambda m: m.group(1) + m.group(2).replace(" ", ""), value).strip()


# ------------------------------------------------------------------------ shared


def _try_ocr(parsed: ParsedEmail) -> str | None:
    if parsed.attachment_path is None:
        return None
    try:
        return ocr_image(parsed.attachment_path)
    except (OcrUnavailableError, FileNotFoundError) as exc:
        logger.warning("OCR unavailable for %s: %s", parsed.source_filename, exc)
        return None


def _group(pattern: re.Pattern[str], text: str, name: str) -> str | None:
    match = pattern.search(text)
    return match.group(name).strip() if match else None


def _first_amount(pattern: re.Pattern[str], text: str) -> Decimal | None:
    match = pattern.search(text)
    return parse_amount(match.group("amount")) if match else None


def _first_nonempty_line(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def _parse_when(text: str) -> datetime | None:
    match = _RIDE_WHEN.search(text) or _DMY_DASHED.search(text)
    if not match:
        return None

    month = _MONTHS.get(match.group("mon").lower())
    if month is None:
        return None

    day, year = int(match.group("day")), int(match.group("year"))
    raw_time = match.groupdict().get("time")
    if not raw_time:
        # Some layouts put the clock time on the following line.
        clock = re.search(r"\b(?P<t>\d{1,2}:\d{2})\b", text[match.end() : match.end() + 40])
        raw_time = clock.group("t") if clock else None

    if not raw_time:
        return datetime.combine(date(year, month, day), datetime.min.time())

    normalised = raw_time.strip().upper().replace(" ", "")
    for fmt in ("%I:%M%p", "%H:%M"):
        try:
            clock_time = datetime.strptime(normalised, fmt).time()
        except ValueError:
            continue
        return datetime.combine(date(year, month, day), clock_time)

    return datetime.combine(date(year, month, day), datetime.min.time())
