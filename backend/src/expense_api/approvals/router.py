"""The approver's queue and the decisions taken from it.

Two things this surface has to get right, and both are authorisation rather than workflow:

- A claim appears to exactly one person at a time - the approver of the current pending step.
  A later level seeing it early would let the chain be short-circuited.
- A decision is pinned to the claim version the approver was shown. SQLite serialises writers,
  so it will not lose an update outright, but serialising is not ordering intent: two approvers
  who both loaded a pending claim would otherwise both write, and the second would overwrite a
  state the first had already moved past. See approvals/service.py.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from expense_api.approvals.service import (
    ConcurrentModificationError,
    NoPendingStepError,
    record_decision,
)
from expense_api.claims.lifecycle import TransitionError
from expense_api.claims.schemas import (
    ApprovalQueueItemResponse,
    RecordDecisionRequest,
    RecordDecisionResponse,
)
from expense_api.claims.serialisers import current_round_steps
from expense_api.db.database import get_async_session
from expense_api.db.models import (
    ApprovalDecision,
    ApprovalStep,
    Employee,
    SettlementClaim,
    TravelRequest,
)
from expense_api.identity.deps import AdminUser
from expense_api.notifications.service import notify_decided

logger = logging.getLogger(__name__)

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_async_session)]

Scope = Literal["pending", "acted"]


@router.get("/approvals", response_model=list[ApprovalQueueItemResponse], tags=["approvals"])
async def approval_queue(
    session: Session,
    user: AdminUser,
    scope: Annotated[Scope, Query()] = "pending",
) -> list[ApprovalQueueItemResponse]:
    """What is on this approver's desk, or what they have already decided.

    `pending` is deliberately narrower than "every step assigned to me that is undecided": a
    step three levels up is assigned and undecided from the day the claim is submitted, and
    showing it would put the same claim in four queues at once.
    """
    claims = await _claims_for(session, user)
    out: list[ApprovalQueueItemResponse] = []

    for claim, request, employee in claims:
        mine = _my_step(claim, user, scope)
        if mine is None:
            continue

        out.append(
            ApprovalQueueItemResponse(
                trq_id=request.trq_id,
                claim_external_id=claim.external_id,
                employee_name=employee.name,
                employee_code=employee.emp_code,
                destination=request.destination_city,
                from_date=request.from_date,
                to_date=request.to_date,
                status=claim.status.value,
                payable=f"{claim.payable:.2f}",
                net_reimbursable=f"{claim.net_reimbursable:.2f}",
                disallowed_total=f"{claim.disallowed_total:.2f}",
                version=claim.version,
                sequence=mine.sequence,
                role=mine.role.value,
                decision=mine.decision.value,
                submitted_at=claim.submitted_at,
                remarks=mine.remarks,
            )
        )

    out.sort(key=lambda item: (item.submitted_at is None, item.submitted_at), reverse=False)
    return out


@router.post(
    "/trips/{trq_id}/claim/decision",
    response_model=RecordDecisionResponse,
    tags=["approvals"],
)
async def decide(
    trq_id: str, payload: RecordDecisionRequest, session: Session, user: AdminUser
) -> RecordDecisionResponse:
    """Approve, reject or return the claim's current step, and tell everyone it moved."""
    if payload.approver_code != user.emp_code:
        # The body names an approver and the header names the caller. If they disagree, refuse
        # rather than trusting either: acting as someone else is the one thing this surface
        # must not allow.
        raise HTTPException(
            status_code=403,
            detail={
                "code": "approver_mismatch",
                "message": "You cannot record a decision on behalf of someone else.",
            },
        )

    request, claim, claimant = await _require_routed_claim(session, trq_id, user)

    steps = current_round_steps(claim)
    pending = [step for step in steps if step.decision is ApprovalDecision.PENDING]
    if not pending:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "nothing_pending",
                "message": "This claim is not waiting on a decision.",
            },
        )
    if pending[0].approver_employee_id != user.id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "not_your_step",
                "message": (
                    f"This claim is with {pending[0].role.value} at step {pending[0].sequence}."
                ),
            },
        )

    decision = ApprovalDecision(payload.decision)
    if decision is ApprovalDecision.RETURNED and not (payload.remarks or "").strip():
        # §2.3: a return goes back to the employee for correction. Without remarks they are
        # told only that it came back, which is the follow-up loop this system exists to close.
        raise HTTPException(
            status_code=422,
            detail={
                "code": "remarks_required",
                "message": "Say what needs correcting before returning a claim.",
            },
        )

    try:
        result = await record_decision(
            session,
            claim_id=claim.id,
            expected_version=payload.expected_version,
            decision=decision,
            approver_employee_id=user.id,
            remarks=payload.remarks,
        )
    except ConcurrentModificationError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "stale_claim", "message": str(exc)}
        ) from exc
    except NoPendingStepError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "nothing_pending", "message": str(exc)}
        ) from exc
    except TransitionError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "invalid_transition", "message": str(exc)}
        ) from exc

    remaining = [
        step
        for step in current_round_steps(claim)
        if step.decision is ApprovalDecision.PENDING and step.sequence > result.step_sequence
    ]
    await notify_decided(
        session,
        claim=claim,
        trq_id=request.trq_id,
        claimant=claimant,
        actor=user,
        decision=decision,
        remarks=payload.remarks,
        next_step=remaining[0] if remaining else None,
    )
    await session.commit()

    return RecordDecisionResponse(
        trq_id=request.trq_id,
        claim_status=result.claim_status.value,
        step_sequence=result.step_sequence,
        new_version=result.new_version,
    )


def _my_step(claim: SettlementClaim, user: Employee, scope: Scope) -> ApprovalStep | None:
    """The step this queue is about, for this person.

    The two scopes look at different things on purpose. `pending` is only ever about the round
    in progress, and only when this person is at the *front* of it - a step three levels up is
    assigned and undecided from the moment the claim is submitted, and showing it would put one
    claim in four queues at once.

    `acted` looks across every round, superseded ones included. A return supersedes the round
    it ends, so filtering to the current round would erase an approver's own history the moment
    someone below them sent the claim back - and "what did I approve?" is exactly the question
    that queue exists to answer.
    """
    if scope == "pending":
        steps = current_round_steps(claim)
        pending = [step for step in steps if step.decision is ApprovalDecision.PENDING]
        if not pending or pending[0].approver_employee_id != user.id:
            return None
        return pending[0]

    decided = [
        step
        for step in claim.approval_steps
        if step.approver_employee_id == user.id and step.decision is not ApprovalDecision.PENDING
    ]
    if not decided:
        return None
    # Most recent round first: after a resubmission the latest decision is the relevant one.
    return max(decided, key=lambda step: (step.submission_round, step.sequence))


async def _claims_for(
    session: AsyncSession, user: Employee
) -> list[tuple[SettlementClaim, TravelRequest, Employee]]:
    rows = (
        (
            await session.execute(
                select(SettlementClaim, TravelRequest, Employee)
                .join(TravelRequest, TravelRequest.id == SettlementClaim.travel_request_id)
                .join(Employee, Employee.id == TravelRequest.employee_id)
                .join(ApprovalStep, ApprovalStep.claim_id == SettlementClaim.id)
                .where(ApprovalStep.approver_employee_id == user.id)
                .options(
                    selectinload(SettlementClaim.approval_steps).selectinload(ApprovalStep.approver)
                )
                .distinct()
            )
        )
        .unique()
        .all()
    )
    return [(claim, request, employee) for claim, request, employee in rows]


async def _require_routed_claim(
    session: AsyncSession, trq_id: str, user: Employee
) -> tuple[TravelRequest, SettlementClaim, Employee]:
    row = (
        await session.execute(
            select(SettlementClaim, TravelRequest, Employee)
            .join(TravelRequest, TravelRequest.id == SettlementClaim.travel_request_id)
            .join(Employee, Employee.id == TravelRequest.employee_id)
            .where(TravelRequest.trq_id == trq_id)
            .options(
                selectinload(SettlementClaim.approval_steps).selectinload(ApprovalStep.approver)
            )
        )
    ).first()

    if row is None:
        raise HTTPException(status_code=404, detail="No such claim")

    claim, request, claimant = row
    if not any(step.approver_employee_id == user.id for step in claim.approval_steps):
        # Never routed to this person, so as far as they are concerned it does not exist.
        raise HTTPException(status_code=404, detail="No such claim")
    return request, claim, claimant
