"""Decide what each message is, before anything tries to extract money from it.

Classification exists so that two documents never reach the extractor:

- Promotional mail, which is noise.
- A payment-failure notice, which carries a merchant, a date and an amount and is still not a
  receipt. The successful charge for the same ride arrives as its own message, so treating the
  failure as a receipt claims the fare twice.

It also separates a vendor's own forward of the claimant's receipt (still the claimant's
receipt) from a colleague forwarding theirs (someone else's expense entirely). Both are
forwards; only the sender tells them apart. The rejection itself belongs to attribution - this
module only has to route it there.
"""

from __future__ import annotations

import re

from expense_api.db.models import DocKind
from expense_api.evidence.ingest import ParsedEmail

INTERNAL_DOMAIN = "nortexindustries.com"

_CAB_VENDOR_DOMAINS = ("uber.com", "olacabs.com")
_TRAVEL_DESK_DOMAINS = ("makemytrip.com",)

# "We could not charge your card", "Payment failed", "Amount due"
_PAYMENT_FAILURE = re.compile(r"payment failed|could not charge|amount due", re.I)
_PROMOTIONAL = re.compile(
    r"\b(\d+%\s*off|flat\s*\d+|monsoon sale|sale is live|unsubscribe|use code)\b", re.I
)
_RIDE_RECEIPT = re.compile(r"thanks for riding", re.I)
_TAX_INVOICE = re.compile(r"tax invoice|folio", re.I)
_ADVANCE = re.compile(r"advance (credited|disbursed)|travel advance", re.I)
_APPROVAL = re.compile(r"travel approval|approval request", re.I)
_APPROVED = re.compile(r"\bapproved\b", re.I)
_FLIGHT = re.compile(r"e-?ticket|flight booking|pnr\b", re.I)
_HOTEL_VOUCHER = re.compile(r"hotel booking voucher|your stay is confirmed", re.I)
_MEAL_BILL = re.compile(r"\b(dinner|lunch|breakfast|bill|restaurant|covers)\b", re.I)

# Document kinds that go on to extraction. Everything else is context or noise.
#
# THIRD_PARTY_FORWARD is included deliberately: the amount has to be extracted so the rejection
# can name a figure and a person. Rejecting it silently here would satisfy the policy and tell
# the employee nothing.
_PRODUCES_CLAIM_LINES = frozenset(
    {
        DocKind.CAB_RECEIPT,
        DocKind.HOTEL_INVOICE,
        DocKind.RESTAURANT_BILL,
        # Company-paid, recorded as a memo row rather than reimbursed (§3.2).
        DocKind.FLIGHT_BOOKING,
        DocKind.THIRD_PARTY_FORWARD,
    }
)


def produces_claim_lines(kind: DocKind) -> bool:
    return kind in _PRODUCES_CLAIM_LINES


def classify(parsed: ParsedEmail, *, claimant_email: str, claimant_name: str) -> DocKind:
    sender = (parsed.sender_email or "").lower()
    subject = parsed.subject or ""
    body = parsed.body_text
    haystack = f"{subject}\n{body}"

    is_claimant = sender == claimant_email.lower()
    is_internal = sender.endswith(f"@{INTERNAL_DOMAIN}")

    # --- vendor mail -------------------------------------------------------------
    # Promotional first: it comes from the same domain as the real bookings, and a discount
    # offer for hotels would otherwise look a lot like a hotel voucher.
    if _from_any(sender, _TRAVEL_DESK_DOMAINS) or sender.startswith("offers@"):
        if _PROMOTIONAL.search(haystack):
            return DocKind.PROMOTIONAL
        if _FLIGHT.search(subject):
            return DocKind.FLIGHT_BOOKING
        if _HOTEL_VOUCHER.search(haystack):
            return DocKind.HOTEL_VOUCHER

    if _from_any(sender, _CAB_VENDOR_DOMAINS):
        # Before the receipt check: the failure notice also mentions a trip.
        if _PAYMENT_FAILURE.search(haystack):
            return DocKind.CAB_PAYMENT_FAILURE
        if _RIDE_RECEIPT.search(body) or "trip with uber" in subject.lower():
            return DocKind.CAB_RECEIPT

    # A hotel's own invoice arrives from the hotel, not the travel desk.
    if _TAX_INVOICE.search(subject):
        return DocKind.HOTEL_INVOICE

    # --- internal mail -----------------------------------------------------------
    if is_internal and not is_claimant:
        # A colleague forwarding a receipt. The body names its own rider, and it is not the
        # claimant - which is what makes this someone else's expense rather than a duplicate.
        if _RIDE_RECEIPT.search(body) and claimant_name.split()[0].lower() not in body.lower():
            return DocKind.THIRD_PARTY_FORWARD
        if parsed.is_forward and _RIDE_RECEIPT.search(body):
            return DocKind.THIRD_PARTY_FORWARD

    # Both halves are required. The travel request in message 01 also says "Advance requested",
    # so the wording alone would misclassify it; and Finance mails about other things too.
    if sender.startswith("finance") and _ADVANCE.search(haystack):
        return DocKind.ADVANCE_NOTICE

    if _APPROVAL.search(subject):
        # The request comes from the claimant; the grant comes back from the approver.
        if is_claimant and not parsed.is_forward:
            return DocKind.APPROVAL_REQUEST
        if _APPROVED.search(body) or subject.lower().startswith(("re:", "rE:")):
            return DocKind.APPROVAL_GRANT
        return DocKind.APPROVAL_REQUEST

    # A bill the employee mailed to themselves to keep. Attachment plus meal wording, rather
    # than attachment alone, so an arbitrary self-mailed image does not become a restaurant.
    if is_claimant and parsed.attachment_path is not None and _MEAL_BILL.search(haystack):
        return DocKind.RESTAURANT_BILL

    return DocKind.UNKNOWN


def _from_any(sender: str, domains: tuple[str, ...]) -> bool:
    return any(sender.endswith(f"@{domain}") or f".{domain}" in sender for domain in domains)
