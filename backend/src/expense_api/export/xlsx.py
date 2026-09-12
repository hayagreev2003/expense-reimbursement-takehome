"""Export a settled claim into the settlement form Finance already knows.

Written into the pack's own template rather than a lookalike, and only into the shaded input
cells. Every total in that sheet is a formula, and the legend says so twice:

    "Every unshaded total is a formula and must not be overwritten."
    "Paid By must be exactly 'Employee' or 'Company' - the settlement summary uses SUMIF."

So the export writes line rows, the disallowed figure and the advance, and lets the workbook
compute payable itself. The point of that is not tidiness: if the spreadsheet's arithmetic and
the application's ever disagree, Finance will believe the spreadsheet, so the two had better be
derived the same way rather than typed in twice.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from expense_api.claims.pipeline import ClaimDraft
from expense_api.db.models import ClaimLineStatus, ExpenseHead, PaidBy

logger = logging.getLogger(__name__)

SHEET = "Expense Settlement Form"

# Input cells, from the template's own layout.
_TRQ_ID = "C5"
_SETTLEMENT_DATE = "F5"
_EMPLOYEE_NAME = "C6"
_EMPLOYEE_CODE = "F6"
_COST_CENTRE = "C7"

# Section row ranges. The row after each block holds its SUM and is never written.
_LODGING_ROWS = range(11, 15)
_TRANSPORT_ROWS = range(19, 29)
_OTHER_ROWS = range(33, 41)

_DISALLOWED_CELL = "H46"
_ADVANCE_CELL = "H48"
_DISALLOWED_REMARK = "I46"

# Statuses that never appear as a row. A rejected line was someone else's expense and was never
# this claim's; a withdrawn one the employee removed. Both stay in the audit trail.
_NOT_ON_THE_FORM = {ClaimLineStatus.REJECTED, ClaimLineStatus.WITHDRAWN}


class FormCapacityError(Exception):
    """More lines than the printed form has rows for."""


def export_settlement(
    claim: ClaimDraft,
    *,
    template: Path,
    destination: Path,
    employee_name: str,
    employee_code: str,
    settlement_date: date | None = None,
) -> Path:
    workbook = load_workbook(template)
    sheet = workbook[SHEET]

    sheet[_TRQ_ID] = claim.travel_request.trq_id
    sheet[_SETTLEMENT_DATE] = (settlement_date or date.today()).strftime("%d-%b-%Y")
    sheet[_EMPLOYEE_NAME] = employee_name
    sheet[_EMPLOYEE_CODE] = employee_code
    sheet[_COST_CENTRE] = claim.travel_request.cost_centre

    lodging, transport, other = _split_by_section(claim)

    _write_lodging(sheet, lodging, claim)
    _write_transport(sheet, transport)
    _write_other(sheet, other)

    # Row 46 carries the disallowed total *with a remark*, per legend line 66. The lines
    # themselves stay in their sections with their amounts, so the SUMIF above still sees them
    # and this row takes them back out - which is what makes the exclusion visible rather than
    # a number that quietly never appeared.
    sheet[_DISALLOWED_CELL] = float(claim.summary.disallowed_total)
    sheet[_DISALLOWED_REMARK] = _disallowed_remark(claim)
    sheet[_ADVANCE_CELL] = float(claim.summary.advance_drawn)

    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(destination)
    logger.info("Exported %s to %s", claim.travel_request.trq_id, destination)
    return destination


def _split_by_section(claim: ClaimDraft):  # type: ignore[no-untyped-def]
    lodging, transport, other = [], [], []

    for outcome in claim.outcomes:
        if outcome.status in _NOT_ON_THE_FORM:
            continue
        if outcome.line.head is ExpenseHead.LODGING:
            lodging.append(outcome)
        elif outcome.line.head is ExpenseHead.TRANSPORT:
            transport.append(outcome)
        else:
            other.append(outcome)

    _check_capacity(lodging, _LODGING_ROWS, "Lodging")
    _check_capacity(transport, _TRANSPORT_ROWS, "Travel & Transportation")
    _check_capacity(other, _OTHER_ROWS, "Other Expenses")
    return lodging, transport, other


def _check_capacity(lines: list, rows: range, section: str) -> None:  # type: ignore[type-arg]
    if len(lines) > len(rows):
        # Refuse rather than silently truncate. A form missing three cab fares looks complete.
        raise FormCapacityError(
            f"{len(lines)} {section} lines will not fit the form's {len(rows)} rows"
        )


def _write_lodging(sheet, lines, claim) -> None:  # type: ignore[no-untyped-def]
    for row, outcome in zip(_LODGING_ROWS, lines, strict=False):
        line = outcome.line
        nights = line.nights or 1
        sheet[f"B{row}"] = _fmt_date(line.line_date)
        sheet[f"C{row}"] = _fmt_date(claim.travel_request.to_date)
        sheet[f"D{row}"] = nights
        sheet[f"E{row}"] = line.description
        sheet[f"F{row}"] = claim.travel_request.destination_city
        sheet[f"G{row}"] = _paid_by(line.paid_by)
        sheet[f"H{row}"] = float(line.claimable)
        sheet[f"I{row}"] = line.proof_ref


def _write_transport(sheet, lines) -> None:  # type: ignore[no-untyped-def]
    for row, outcome in zip(_TRANSPORT_ROWS, lines, strict=False):
        line = outcome.line
        origin, _, destination = line.description.partition(" to ")
        sheet[f"B{row}"] = _fmt_date(line.line_date)
        sheet[f"D{row}"] = origin
        sheet[f"E{row}"] = destination or ""
        sheet[f"F{row}"] = "Cab" if "to" in line.description else "Air"
        sheet[f"G{row}"] = _paid_by(line.paid_by)
        sheet[f"H{row}"] = float(line.claimable)
        sheet[f"I{row}"] = line.proof_ref


def _write_other(sheet, lines) -> None:  # type: ignore[no-untyped-def]
    for row, outcome in zip(_OTHER_ROWS, lines, strict=False):
        line = outcome.line
        sheet[f"B{row}"] = _fmt_date(line.line_date)
        sheet[f"C{row}"] = line.head.value
        sheet[f"D{row}"] = line.description
        sheet[f"G{row}"] = _paid_by(line.paid_by)
        sheet[f"H{row}"] = float(line.claimable)
        sheet[f"I{row}"] = line.proof_ref


def _paid_by(value: PaidBy) -> str:
    """Exactly 'Employee' or 'Company'. The summary's SUMIF matches on this string."""
    return value.value


def _fmt_date(value: date | None) -> str:
    return value.strftime("%d-%b-%Y") if value else ""


def _disallowed_remark(claim: ClaimDraft) -> str:
    """Name what was taken out. A bare number on row 46 invites the query it should prevent."""
    parts = [
        f"{o.line.description} {o.disallowed_amount}"
        for o in claim.outcomes
        if o.disallowed_amount > Decimal("0.00")
    ]
    rejected = [o for o in claim.outcomes if o.status is ClaimLineStatus.REJECTED]
    if rejected:
        parts.append(
            f"{len(rejected)} item(s) rejected as another person's expense (§4), not shown above"
        )
    return "; ".join(parts) or "None"
