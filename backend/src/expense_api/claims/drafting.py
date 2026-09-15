"""Turn extracted items into draft claim lines.

Everything here happens before policy evaluation. The job is to say what each line *is* -
which head it falls under, who paid it, whose expense it is - so the rule engine has something
well-formed to judge. Getting the head wrong is not a cosmetic error: it decides which limit
applies, and in-room dining filed as a folio extra rather than a meal loses the employee 1,120.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from expense_api.claims.attribution import Attribution, attribute, derive_paid_by
from expense_api.db.models import ClaimLineStatus, DocKind, ExpenseHead, PaidBy
from expense_api.evidence.extractors.base import ExtractedItem

# Folio labels that are food. §4 lists laundry, mini bar, in-room entertainment, spa and gym -
# it does not list food, so a meal on a folio is a meal (R19).
_FOOD = re.compile(r"\b(dining|restaurant|meal|breakfast|lunch|dinner|food|cafe|bar snack)\b", re.I)
_LODGING = re.compile(r"\b(room|tariff|accommodation|lodging|stay)\b", re.I)

# Wording that makes a meal Business Entertainment rather than the employee's own meal (§3.5).
_HOSTED = re.compile(
    r"\b(client|customer|procurement|vendor|partner|supplier|team from|hosted|guests?)\b", re.I
)


@dataclass(frozen=True, slots=True)
class DraftContext:
    """What drafting needs to know about the trip, beyond the item itself."""

    claimant_name: str
    company_name: str | None = None
    # The customer being visited, from the travel request. Naming them in a bill's note is the
    # clearest signal that a meal was hosted rather than eaten alone.
    visiting_company: str | None = None
    # The employee's own note on the message, e.g. "Dinner with Vertex procurement team".
    note: str | None = None


@dataclass(frozen=True, slots=True)
class DraftLine:
    head: ExpenseHead
    description: str
    line_date: date | None
    paid_by: PaidBy
    gross_amount: object
    status: ClaimLineStatus
    status_reason: str | None
    nights: int | None
    source_index: int


def classify_head(
    kind: DocKind, description: str, *, context: DraftContext | None = None
) -> ExpenseHead:
    """Which policy head this line falls under."""
    if kind in (DocKind.CAB_RECEIPT, DocKind.THIRD_PARTY_FORWARD, DocKind.FLIGHT_BOOKING):
        return ExpenseHead.TRANSPORT

    if kind is DocKind.HOTEL_INVOICE:
        # Food is checked before lodging, and the order is load-bearing: "In-room dining"
        # contains "room", so a lodging-first check files the meal as accommodation. It would
        # then be measured against the per-night tariff limit instead of the daily meal cap,
        # and the employee loses 1,120 they are entitled to.
        if _FOOD.search(description):
            return ExpenseHead.MEALS
        if _LODGING.search(description):
            return ExpenseHead.LODGING
        # Laundry, mini bar and the rest. Policy will disallow them by name; they are not
        # dropped here, because a disallowed line has to be visible with its reason.
        return ExpenseHead.MISC

    if kind is DocKind.RESTAURANT_BILL:
        return ExpenseHead.BUSINESS_ENTERTAINMENT if _is_hosted(context) else ExpenseHead.MEALS

    return ExpenseHead.MISC


def _is_hosted(context: DraftContext | None) -> bool:
    """§3.5: a meal hosted for a customer or partner is not meal allowance.

    Decided from what the employee wrote and who the trip was to visit. Deliberately
    conservative in the direction of Business Entertainment, because that head *holds* the line
    for attendee names and prior approval rather than quietly paying it - the safer error.
    """
    if context is None:
        return False

    note = context.note or ""
    if context.visiting_company and context.visiting_company.split()[0].lower() in note.lower():
        return True
    return bool(_HOSTED.search(note))


def draft_line(
    item: ExtractedItem,
    kind: DocKind,
    *,
    context: DraftContext,
    source_index: int,
) -> DraftLine:
    """One extracted item, classified and attributed but not yet judged by policy."""
    who = attribute(item.payer_name, claimant_name=context.claimant_name)
    paid_by = derive_paid_by(item.payment_method, company_name=context.company_name)

    if who.attribution is Attribution.THIRD_PARTY:
        status, reason = ClaimLineStatus.REJECTED, who.reason
    elif paid_by is PaidBy.COMPANY:
        # Recorded for audit and policy checking, excluded from the reimbursable total (§3.2).
        status, reason = (
            ClaimLineStatus.MEMO,
            "Paid by the company on the corporate card; recorded for audit, not reimbursed.",
        )
    else:
        status, reason = ClaimLineStatus.ALLOWED, None

    return DraftLine(
        head=classify_head(kind, item.description, context=context),
        description=item.description,
        line_date=item.txn_date or (item.txn_datetime.date() if item.txn_datetime else None),
        paid_by=paid_by,
        gross_amount=item.gross_amount,
        status=status,
        status_reason=reason,
        nights=item.nights,
        source_index=source_index,
    )


def find_coverage_gaps(
    *,
    trip_from: date,
    trip_to: date,
    stays: Sequence[tuple[date, int]],
) -> list[date]:
    """Nights of the trip with no accommodation evidence behind them (R25).

    Flagged, never filled. The sample trip runs 16-20 Jun with a folio covering three nights
    from the 16th, so the night of the 19th is unaccounted for while the return flight is not
    until the evening of the 20th. Something happened that night; the system does not know
    what, and inventing a line would be worse than saying so.

    Every stay counts, not just one. A trip can carry two hotel bills - one mailed, one the
    employee forwards later - and reading only the most recent would report the nights the
    first one covers as unaccounted for.
    """
    nights_needed = {
        trip_from + timedelta(days=offset) for offset in range((trip_to - trip_from).days)
    }

    covered = {
        check_in + timedelta(days=offset) for check_in, nights in stays for offset in range(nights)
    }

    return sorted(nights_needed - covered)
