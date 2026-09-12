"""Turn a ClaimDraft into wire models.

Kept apart from the router so the shape the UI sees is defined in one place, and so the
acceptance test can assert on the same serialisation the browser receives.
"""

from __future__ import annotations

from datetime import date

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
    )
