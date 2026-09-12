"""Freezing a computed draft into rows at submission time.

Up to submission a claim is *computed*: evidence in, lines out, every run identical. That is
the right model while the employee is still adding bills, because it means there is no second
copy of the figures to get out of step with the evidence.

The moment it is submitted that stops being right. An approver is signing off on a specific set
of lines at a specific value, and what they signed off on has to survive the employee uploading
another bill, an OCR change, or a policy revision. So submission writes the draft down - lines,
the policy decisions behind them, the totals, and the approval chain that the value resolved to
- and everything downstream reads the rows, not a recomputation.

A resubmission after a return (§2.3) rewrites the lines against the same Travel Request ID and
opens a new approval round. The previous round's steps are already marked superseded by the
return itself, so the history of who approved what value stays intact.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from expense_api.claims.lifecycle import assert_transition
from expense_api.claims.pipeline import ClaimDraft
from expense_api.db.models import (
    ApprovalDecision,
    ApprovalStep,
    ClaimEvent,
    ClaimLine,
    ClaimStatus,
    Employee,
    PolicyDecision,
    SettlementClaim,
)

logger = logging.getLogger(__name__)


class NotSubmittable(Exception):
    """The claim is not in a state that can be submitted."""


async def load_claim(session: AsyncSession, travel_request_id: int) -> SettlementClaim | None:
    return (
        await session.execute(
            select(SettlementClaim)
            .where(SettlementClaim.travel_request_id == travel_request_id)
            .options(
                selectinload(SettlementClaim.lines).selectinload(ClaimLine.decisions),
                selectinload(SettlementClaim.approval_steps).selectinload(ApprovalStep.approver),
            )
        )
    ).scalar_one_or_none()


async def submit(
    session: AsyncSession, *, draft: ClaimDraft, claimant: Employee
) -> SettlementClaim:
    """Write the draft down and start the approval chain. Caller commits."""
    if not draft.can_submit:
        raise NotSubmittable("; ".join(draft.blocking_reasons))

    request = draft.travel_request
    claim = await load_claim(session, request.id)

    if claim is None:
        claim = SettlementClaim(
            travel_request_id=request.id,
            policy_version_id=await _policy_version_id(session, draft),
            status=ClaimStatus.DRAFT,
        )
        session.add(claim)
        await session.flush()
    elif claim.status is not ClaimStatus.DRAFT:
        # Not a transition error dressed up as a 500: an already-submitted claim is a state the
        # UI can and does reach by double-clicking, and it deserves a sentence a human reads.
        raise NotSubmittable(
            f"This claim is already {claim.status.value.replace('_', ' ')}. "
            "It can only be resubmitted after an approver returns it."
        )
    else:
        await _clear_lines(session, claim)

    assert_transition(claim.status, ClaimStatus.PENDING_APPROVAL)

    _write_lines(session, claim, draft)
    _write_summary(claim, draft)

    steps = await _write_chain(session, claim, draft)

    claim.status = ClaimStatus.PENDING_APPROVAL
    claim.submitted_at = datetime.now(UTC)
    claim.version += 1

    session.add(
        ClaimEvent(
            claim_id=claim.id,
            travel_request_id=request.id,
            actor_employee_id=claimant.id,
            action="claim_submitted",
            payload={
                "round": claim.return_count + 1,
                "net_reimbursable": f"{draft.summary.net_reimbursable:.2f}",
                "payable": f"{draft.summary.payable:.2f}",
                "chain": [f"{step.sequence}:{step.role.value}" for step in steps],
            },
        )
    )
    await session.flush()
    logger.info("Claim %s submitted for %s", claim.external_id, request.trq_id)
    return claim


async def _policy_version_id(session: AsyncSession, draft: ClaimDraft) -> int:
    """The version the draft was evaluated against, not simply the newest one.

    Re-derived here rather than threaded through ClaimDraft so there is exactly one query that
    answers "which policy is in force for these dates" - the one in the pipeline - and this
    reads the same row it chose.
    """
    from expense_api.claims.pipeline import policy_for

    version = await policy_for(session, draft.travel_request)
    return version.id


async def _clear_lines(session: AsyncSession, claim: SettlementClaim) -> None:
    """A resubmission replaces the previous draft's lines outright.

    Safe because nothing has been approved against them: the claim is back in draft, which only
    happens on a return, and a return supersedes every step of the round it ends.
    """
    for line in list(claim.lines):
        await session.delete(line)
    await session.flush()


def _write_lines(session: AsyncSession, claim: SettlementClaim, draft: ClaimDraft) -> None:
    for outcome in draft.outcomes:
        line = ClaimLine(
            claim_id=claim.id,
            head=outcome.line.head,
            line_date=outcome.line.line_date,
            description=outcome.line.description,
            paid_by=outcome.line.paid_by,
            # The claimable figure, tax included. `gross_amount` on the evidence is pre-tax for
            # a bill that quotes its lines that way, and storing that would make the persisted
            # claim disagree with the total the employee submitted.
            gross_amount=outcome.line.claimable,
            allowed_amount=outcome.allowed_amount,
            disallowed_amount=outcome.disallowed_amount,
            status=outcome.status,
            proof_ref=outcome.line.proof_ref,
            status_reason=outcome.line.preset_reason,
        )
        # Added to the session with its FK set rather than appended to `claim.lines`:
        # appending would touch the lazy collection, and on an async session that is a query
        # from a place that cannot await one.
        session.add(line)

        for decision in outcome.decisions:
            line.decisions.append(
                PolicyDecision(
                    rule_id=decision.rule_id,
                    outcome=decision.outcome,
                    amount_effect=decision.amount_effect,
                    reason=decision.reason,
                    policy_citation=decision.citation,
                )
            )


def _write_summary(claim: SettlementClaim, draft: ClaimDraft) -> None:
    summary = draft.summary
    claim.employee_paid_gross = summary.employee_paid_gross
    claim.company_paid_memo = summary.company_paid_memo
    claim.disallowed_total = summary.disallowed_total
    claim.net_reimbursable = summary.net_reimbursable
    claim.advance_drawn = summary.advance_drawn
    claim.payable = summary.payable
    claim.recoverable = summary.recoverable


async def _write_chain(
    session: AsyncSession, claim: SettlementClaim, draft: ClaimDraft
) -> list[ApprovalStep]:
    """Persist the chain the *current value* resolved to, as a new round.

    Resolved from the value after disallowances, so withdrawing a held line can drop the claim
    into a lower band and shed a level - which is why this is written at submission rather than
    computed when an approver opens it.
    """
    codes = [step.approver.emp_code for step in draft.chain if step.approver]
    directory = {
        person.emp_code: person
        for person in (
            (await session.execute(select(Employee).where(Employee.emp_code.in_(codes))))
            .scalars()
            .all()
        )
    }
    round_number = claim.return_count + 1
    steps: list[ApprovalStep] = []

    for step in draft.chain:
        approver = directory.get(step.approver.emp_code) if step.approver else None
        # A level nobody above the claimant fills (§2.2) is closed at submission rather than
        # left pending. Left pending it would be the step the claim is waiting on, addressed to
        # nobody, and the claim would never move. It carries the routing note as its remark, so
        # the audit says why it was closed and by what rule.
        skipped = approver is None
        row = ApprovalStep(
            claim_id=claim.id,
            sequence=step.sequence,
            role=step.role,
            approver_employee_id=approver.id if approver else None,
            decision=ApprovalDecision.APPROVED if skipped else ApprovalDecision.PENDING,
            decided_at=datetime.now(UTC) if skipped else None,
            remarks=step.note if skipped else None,
            submission_round=round_number,
            superseded=False,
        )
        session.add(row)
        steps.append(row)

    return steps
