"""Run the whole pipeline for one trip: evidence in, settled claim out.

This is the seam every other surface goes through - the API, the seed, and the acceptance test
all call `build_claim`. Having one path means the figures a reviewer sees in the UI are produced
by the same code the test asserts on, rather than by a parallel implementation that agrees with
it today.

    ingest -> classify -> extract -> reconcile -> dedup -> attribute -> policy -> summary -> route
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.approvals.routing import ChainStep, EmployeeRef, resolve_chain
from expense_api.claims.drafting import DraftContext, draft_line, find_coverage_gaps
from expense_api.claims.lifecycle import check_can_submit
from expense_api.claims.summary import SettlementSummary, summarise
from expense_api.db.models import (
    Advance,
    ClaimLineStatus,
    DocKind,
    Employee,
    EvidenceDocument,
    ExtractionStatus,
    PolicyVersion,
    TravelRequest,
)
from expense_api.evidence.classify import produces_claim_lines
from expense_api.evidence.dedup import DedupResult, find_duplicates
from expense_api.evidence.extractors.base import ExtractedItem, ExtractionResult, Extractor
from expense_api.evidence.extractors.registry import get_extractor
from expense_api.evidence.ingest import AttachmentNotFoundError, EmailParseError, parse_eml
from expense_api.policy.engine import LineOutcome, evaluate_lines
from expense_api.policy.registry import EvaluationContext, LineUnderReview
from expense_api.policy.tax import apportion_tax

logger = logging.getLogger(__name__)

_ZERO = Decimal("0.00")


@dataclass
class ClaimDraft:
    """Everything the review screen and the acceptance test need about one claim."""

    travel_request: TravelRequest
    outcomes: list[LineOutcome]
    summary: SettlementSummary
    chain: list[ChainStep]
    dedup: DedupResult
    coverage_gaps: list[Any] = field(default_factory=list)
    needs_input: dict[str, str] = field(default_factory=dict)
    set_aside: dict[str, str] = field(default_factory=dict)

    @property
    def can_submit(self) -> bool:
        return check_can_submit(self.outcomes).can_submit

    @property
    def blocking_reasons(self) -> list[str]:
        return check_can_submit(self.outcomes).blocking_reasons

    def lines_with_status(self, status: ClaimLineStatus) -> list[LineOutcome]:
        return [outcome for outcome in self.outcomes if outcome.status is status]


async def build_claim(
    session: AsyncSession,
    *,
    travel_request: TravelRequest,
    emails_dir: Path,
    receipts_dir: Path,
    withdrawn_descriptions: frozenset[str] = frozenset(),
    extractor: Extractor | None = None,
) -> ClaimDraft:
    """Evaluate every piece of evidence attached to a trip into a settled claim."""
    engine = extractor or get_extractor()

    employee = (
        await session.execute(select(Employee).where(Employee.id == travel_request.employee_id))
    ).scalar_one()
    policy = await policy_for(session, travel_request)
    documents = await _documents_for(session, travel_request)
    advance_drawn = await _advance_for(session, travel_request)

    context = DraftContext(
        claimant_name=employee.name,
        company_name="Nortex Industries Ltd",
        visiting_company=travel_request.visiting_company,
    )

    items: list[ExtractedItem] = []
    tax_shares: list[Decimal] = []
    kinds: list[DocKind] = []
    proofs: list[str] = []
    notes: list[str | None] = []
    needs_input: dict[str, str] = {}
    set_aside: dict[str, str] = {}
    lodging_check_in = None
    lodging_nights = None

    for document in documents:
        if not produces_claim_lines(document.doc_kind):
            set_aside[document.source_filename] = _why_set_aside(document.doc_kind)
            continue

        try:
            message_path, attachment_dir = _locate(document, emails_dir, receipts_dir)
            parsed = parse_eml(message_path, receipts_dir=attachment_dir)
        except (AttachmentNotFoundError, EmailParseError, OSError, ValueError) as exc:
            # One unreadable document must not take the other fourteen down with it, and it
            # must not vanish either: it surfaces as needs-input, which is visible and blocks
            # submission, rather than as a 500 or a silently shorter claim.
            logger.warning("Could not read %s: %s", document.source_filename, exc)
            needs_input[document.source_filename] = f"This document could not be read: {exc}"
            document.extraction_status = ExtractionStatus.NEEDS_INPUT
            document.needs_input_reason = str(exc)
            continue

        result = engine.extract(parsed, document.doc_kind)

        if result.status is ExtractionStatus.NEEDS_INPUT:
            # The reconciliation guard, or a missing required field. No claim lines are created
            # from an unbalanced document; a human resolves it first.
            needs_input[document.source_filename] = result.needs_input_reason or "Needs review."
            document.extraction_status = ExtractionStatus.NEEDS_INPUT
            document.needs_input_reason = result.needs_input_reason
            continue

        document.extraction_status = ExtractionStatus.EXTRACTED
        document.extractor_name = result.extractor_name

        for item, tax_share in _with_tax_shares(result):
            items.append(item)
            tax_shares.append(tax_share)
            kinds.append(document.doc_kind)
            proofs.append(document.proof_ref)
            notes.append(document.body_text)
            if document.doc_kind is DocKind.HOTEL_INVOICE and item.nights:
                lodging_check_in, lodging_nights = item.txn_date, item.nights

    dedup = find_duplicates(items)

    lines: list[LineUnderReview] = []
    presets: dict[int, ClaimLineStatus] = {}

    for position, index in enumerate(dedup.kept):
        item, kind = items[index], kinds[index]
        line_context = DraftContext(
            claimant_name=context.claimant_name,
            company_name=context.company_name,
            visiting_company=context.visiting_company,
            note=notes[index],
        )
        drafted = draft_line(item, kind, context=line_context, source_index=index)

        if drafted.description in withdrawn_descriptions:
            presets[position] = ClaimLineStatus.WITHDRAWN
        elif drafted.status in (ClaimLineStatus.REJECTED, ClaimLineStatus.MEMO):
            presets[position] = drafted.status

        lines.append(
            LineUnderReview(
                head=drafted.head,
                description=drafted.description,
                gross_amount=item.gross_amount,
                tax_share=tax_shares[index],
                paid_by=drafted.paid_by,
                line_date=drafted.line_date,
                nights=drafted.nights,
                proof_ref=proofs[index],
                preset_reason=drafted.status_reason,
            )
        )

    outcomes = evaluate_lines(
        lines, _evaluation_context(travel_request, policy, employee.name), preset_statuses=presets
    )
    summary = summarise(outcomes, advance_drawn=advance_drawn)

    chain = resolve_chain(
        claim_value=summary.net_reimbursable,
        claimant=await _employee_ref(session, employee),
        directory=await _directory(session),
        params=policy.payload,
    )

    return ClaimDraft(
        travel_request=travel_request,
        outcomes=outcomes,
        summary=summary,
        chain=chain,
        dedup=dedup,
        coverage_gaps=find_coverage_gaps(
            trip_from=travel_request.from_date,
            trip_to=travel_request.to_date,
            lodging_check_in=lodging_check_in,
            lodging_nights=lodging_nights,
        ),
        needs_input=needs_input,
        set_aside=set_aside,
    )


def _with_tax_shares(result: ExtractionResult) -> list[tuple[ExtractedItem, Decimal]]:
    """Pair each line with the bill-level tax to be *added* to it.

    The distinction matters and is easy to get wrong. An extracted item's `tax_amount` is a
    component of its gross - a cab receipt's 90.02 of tax is already inside its 1,415.02 total,
    and a restaurant's GST is inside the printed total. Adding those on top double-counts them.

    Only a bill whose lines are quoted *pre-tax* has tax to apportion, and it announces itself
    by stating a subtotal and a larger total: the hotel folio's four lines sum to 19,200 against
    a 21,504 total, so 2,304 is genuinely additional. Everything else gets a zero share.
    """
    items = list(result.items)
    if not items:
        return []

    if result.stated_subtotal is None or result.stated_total is None:
        return [(item, _ZERO) for item in items]

    tax = (result.stated_total - result.stated_subtotal).quantize(Decimal("0.01"))
    if tax <= _ZERO:
        return [(item, _ZERO) for item in items]

    shares = apportion_tax([item.gross_amount for item in items], tax)
    return list(zip(items, shares, strict=True))


def _locate(
    document: EvidenceDocument, emails_dir: Path, receipts_dir: Path
) -> tuple[Path, Path]:
    """Where this document's message and its attachments actually are.

    Pack evidence lives in the pack's two directories. An employee upload lives beside its own
    attachment under the upload directory, and carries `source_path` saying so - otherwise the
    pipeline would look for it in a read-only directory it will never be in.
    """
    if document.source_path:
        path = Path(document.source_path)
        return path, path.parent
    return emails_dir / document.source_filename, receipts_dir


def _why_set_aside(kind: DocKind) -> str:
    match kind:
        case DocKind.PROMOTIONAL:
            return "Promotional mail; not evidence of an expense."
        case DocKind.CAB_PAYMENT_FAILURE:
            return (
                "A payment-failure notice, not a receipt. The successful charge for this trip "
                "arrived separately."
            )
        case DocKind.HOTEL_VOUCHER:
            return "Booking voucher; the tax invoice is the claimable document."
        case DocKind.APPROVAL_REQUEST | DocKind.APPROVAL_GRANT:
            return "Part of the approval thread for this trip."
        case DocKind.ADVANCE_NOTICE:
            return "Advance disbursement notice; settled against the claim total."
        case _:
            return "Not a claimable document."


def _evaluation_context(
    travel_request: TravelRequest, policy: PolicyVersion, claimant_name: str
) -> EvaluationContext:
    return EvaluationContext(
        params=policy.payload,
        city_class=travel_request.city_class.value,
        trip_from=travel_request.from_date,
        trip_to=travel_request.to_date,
        claimant_name=claimant_name,
    )


async def policy_for(session: AsyncSession, request: TravelRequest) -> PolicyVersion:
    """The version in force for the trip's dates, not simply the newest one."""
    version = (
        (
            await session.execute(
                select(PolicyVersion)
                .where(PolicyVersion.effective_from <= request.from_date)
                .order_by(PolicyVersion.effective_from.desc())
            )
        )
        .scalars()
        .first()
    )

    if version is None:
        raise ValueError(f"No policy version is in force for travel from {request.from_date}")
    return version


async def _documents_for(session: AsyncSession, request: TravelRequest) -> list[EvidenceDocument]:
    return list(
        (
            await session.execute(
                select(EvidenceDocument)
                .where(EvidenceDocument.travel_request_id == request.id)
                .order_by(EvidenceDocument.source_filename)
            )
        )
        .scalars()
        .all()
    )


async def _advance_for(session: AsyncSession, request: TravelRequest) -> Decimal:
    total = (
        (await session.execute(select(Advance).where(Advance.travel_request_id == request.id)))
        .scalars()
        .all()
    )
    return sum((row.amount for row in total), _ZERO)


async def _employee_ref(session: AsyncSession, employee: Employee) -> EmployeeRef:
    return EmployeeRef(
        emp_code=employee.emp_code,
        name=employee.name,
        role=employee.role,
        reporting_manager_code=employee.reporting_manager_code,
    )


async def _directory(session: AsyncSession) -> dict[str, EmployeeRef]:
    people = (await session.execute(select(Employee))).scalars().all()
    return {
        person.emp_code: EmployeeRef(
            emp_code=person.emp_code,
            name=person.name,
            role=person.role,
            reporting_manager_code=person.reporting_manager_code,
        )
        for person in people
    }
