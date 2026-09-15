"""Turn a ClaimDraft into wire models.

Kept apart from the router so the shape the UI sees is defined in one place, and so the
acceptance test can assert on the same serialisation the browser receives.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from expense_api.approvals.routing import ChainStep
from expense_api.claims.pipeline import ClaimDraft
from expense_api.claims.schemas import (
    ApprovalStepResponse,
    ClaimLineResponse,
    ClaimResponse,
    PolicyDecisionResponse,
    SetAsideDocumentResponse,
    SettlementSummaryResponse,
    SuppressedDuplicateResponse,
)
from expense_api.db.models import (
    ApprovalStep,
    EvidenceDocument,
    ExtractionStatus,
    SettlementClaim,
    TravelRequest,
)
from expense_api.evidence import corrections


def to_chain(chain: list[ChainStep]) -> list[ApprovalStepResponse]:
    return [
        ApprovalStepResponse(
            sequence=step.sequence,
            role=step.role.value,
            approver_name=step.approver.name if step.approver else None,
            approver_code=step.approver.emp_code if step.approver else None,
            note=step.note,
        )
        for step in chain
    ]


def to_claim_response(claim: ClaimDraft, *, employee_name: str, deadline: date) -> ClaimResponse:
    request = claim.travel_request

    lines = [
        ClaimLineResponse(
            index=index,
            head=outcome.line.head.value,
            description=outcome.line.description,
            line_date=outcome.line.line_date,
            paid_by=outcome.line.paid_by.value,
            gross_amount=f"{outcome.line.gross_amount:.2f}",
            tax_share=f"{outcome.line.tax_share:.2f}",
            allowed_amount=f"{outcome.allowed_amount:.2f}",
            disallowed_amount=f"{outcome.disallowed_amount:.2f}",
            status=outcome.status.value,
            proof_ref=outcome.line.proof_ref,
            nights=outcome.line.nights,
            decisions=[
                PolicyDecisionResponse(
                    rule_id=decision.rule_id,
                    outcome=decision.outcome.value,
                    reason=decision.reason,
                    citation=decision.citation,
                    amount_effect=f"{decision.amount_effect:.2f}",
                )
                for decision in outcome.decisions
            ],
        )
        for index, outcome in enumerate(claim.outcomes)
    ]

    summary = claim.summary
    return ClaimResponse(
        trq_id=request.trq_id,
        employee_name=employee_name,
        destination=request.destination_city,
        city_class=request.city_class.value,
        from_date=request.from_date,
        to_date=request.to_date,
        status="draft",
        submission_deadline=deadline,
        lines=lines,
        summary=SettlementSummaryResponse(
            employee_paid_gross=f"{summary.employee_paid_gross:.2f}",
            company_paid_memo=f"{summary.company_paid_memo:.2f}",
            disallowed_total=f"{summary.disallowed_total:.2f}",
            net_reimbursable=f"{summary.net_reimbursable:.2f}",
            advance_drawn=f"{summary.advance_drawn:.2f}",
            payable=f"{summary.payable:.2f}",
            recoverable=f"{summary.recoverable:.2f}",
        ),
        chain=to_chain(claim.chain),
        can_submit=claim.can_submit,
        blocking_reasons=claim.blocking_reasons,
        coverage_gaps=list(claim.coverage_gaps),
        set_aside=[
            SetAsideDocumentResponse(source_filename=name, reason=reason)
            for name, reason in sorted(claim.set_aside.items())
        ],
        suppressed_duplicates=[
            SuppressedDuplicateResponse(reason=match.reason, strength=match.strength.value)
            for match in claim.dedup.suppressed
        ],
        needs_input=[
            SetAsideDocumentResponse(source_filename=name, reason=reason)
            for name, reason in sorted(claim.needs_input.items())
        ],
        manually_entered=[
            SetAsideDocumentResponse(source_filename=name, reason=reason)
            for name, reason in sorted(claim.manually_entered.items())
        ],
    )


def current_round_steps(claim: SettlementClaim) -> list[ApprovalStep]:
    """The chain the claim is actually being judged on.

    A returned claim supersedes its round rather than deleting it, so the rows for earlier
    rounds are still there - showing them alongside the live ones would tell an approver the
    claim has been approved twice.
    """
    return sorted(
        (
            step
            for step in claim.approval_steps
            if not step.superseded and step.submission_round == claim.return_count + 1
        ),
        key=lambda step: step.sequence,
    )


def to_persisted_chain(claim: SettlementClaim) -> list[ApprovalStepResponse]:
    return [
        ApprovalStepResponse(
            sequence=step.sequence,
            role=step.role.value,
            approver_name=step.approver.name if step.approver else None,
            approver_code=step.approver.emp_code if step.approver else None,
            note=None,
            decision=step.decision.value,
            decided_at=step.decided_at,
            remarks=step.remarks,
        )
        for step in current_round_steps(claim)
    ]


def to_persisted_claim_response(
    claim: SettlementClaim,
    *,
    request: TravelRequest,
    employee_name: str,
    deadline: date,
    documents: list[EvidenceDocument],
    awaiting_me: bool = False,
) -> ClaimResponse:
    """The submitted claim, read back from its rows.

    Once a claim is submitted this - not a re-evaluation of the evidence - is what every
    surface renders. An approver has to see the figures that were submitted to them, and a
    recomputation is a different number the moment anything behind it moves.
    """
    lines = [
        ClaimLineResponse(
            index=index,
            head=line.head.value,
            description=line.description,
            line_date=line.line_date,
            paid_by=line.paid_by.value,
            gross_amount=f"{line.gross_amount:.2f}",
            # Already folded into the stored gross - the persisted line is the claimable
            # figure, so showing a share here again would read as double counting.
            tax_share=f"{Decimal('0.00'):.2f}",
            allowed_amount=f"{line.allowed_amount:.2f}",
            disallowed_amount=f"{line.disallowed_amount:.2f}",
            status=line.status.value,
            proof_ref=line.proof_ref,
            nights=None,
            decisions=[
                PolicyDecisionResponse(
                    rule_id=decision.rule_id,
                    outcome=decision.outcome.value,
                    reason=decision.reason,
                    citation=decision.policy_citation,
                    amount_effect=f"{decision.amount_effect:.2f}",
                )
                for decision in line.decisions
            ],
        )
        for index, line in enumerate(
            sorted(claim.lines, key=lambda row: (row.line_date or date.max, row.id))
        )
    ]

    return ClaimResponse(
        trq_id=request.trq_id,
        employee_name=employee_name,
        destination=request.destination_city,
        city_class=request.city_class.value,
        from_date=request.from_date,
        to_date=request.to_date,
        status=claim.status.value,
        submission_deadline=deadline,
        lines=lines,
        summary=SettlementSummaryResponse(
            employee_paid_gross=f"{claim.employee_paid_gross:.2f}",
            company_paid_memo=f"{claim.company_paid_memo:.2f}",
            disallowed_total=f"{claim.disallowed_total:.2f}",
            net_reimbursable=f"{claim.net_reimbursable:.2f}",
            advance_drawn=f"{claim.advance_drawn:.2f}",
            payable=f"{claim.payable:.2f}",
            recoverable=f"{claim.recoverable:.2f}",
        ),
        chain=to_persisted_chain(claim),
        can_submit=False,
        blocking_reasons=[],
        coverage_gaps=[],
        # Rebuilt from the evidence rows rather than stored: which documents were set aside is
        # a property of their kind, and an approver asking "did it see the promo mail?" should
        # get an answer after submission too.
        set_aside=[
            SetAsideDocumentResponse(
                source_filename=document.source_filename, reason=_set_aside_reason(document)
            )
            for document in sorted(documents, key=lambda row: row.source_filename)
            if document.extraction_status is ExtractionStatus.NOT_APPLICABLE
        ],
        suppressed_duplicates=[],
        needs_input=[
            SetAsideDocumentResponse(
                source_filename=document.source_filename,
                reason=document.needs_input_reason or "Needs review.",
            )
            for document in sorted(documents, key=lambda row: row.source_filename)
            if document.extraction_status is ExtractionStatus.NEEDS_INPUT
        ],
        manually_entered=[
            SetAsideDocumentResponse(
                source_filename=document.source_filename,
                reason=(
                    "Figures entered by the claimant; nothing could be read from the document."
                ),
            )
            for document in sorted(documents, key=lambda row: row.source_filename)
            if corrections.names_a_human(document)
        ],
        version=claim.version,
        submitted_at=claim.submitted_at,
        return_count=claim.return_count,
        frozen=True,
        awaiting_me=awaiting_me,
    )


def _set_aside_reason(document: EvidenceDocument) -> str:
    from expense_api.claims.pipeline import _why_set_aside

    return _why_set_aside(document.doc_kind)
