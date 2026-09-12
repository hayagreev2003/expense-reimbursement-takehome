"""Recording approval decisions against a claim.

Every write is pinned to the claim version the caller last read. SQLite serialises writers, so
it will not lose an update outright, but serialising is not the same as ordering intent: two
approvers who both loaded a pending claim would otherwise both write a decision, and the second
would silently overwrite a state the first had already moved on from.

The version check is therefore the thing actually preventing a double decision here, not the
storage engine's locking. It is what the concurrency test exercises, and it would still be
correct on Postgres.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from expense_api.claims.lifecycle import assert_transition
from expense_api.db.models import (
    ApprovalDecision,
    ApprovalStep,
    ClaimEvent,
    ClaimStatus,
    SettlementClaim,
)

logger = logging.getLogger(__name__)


class ConcurrentModificationError(Exception):
    """Someone else changed this claim since it was read."""


class NoPendingStepError(Exception):
    """There is nothing awaiting a decision on this claim."""


@dataclass(frozen=True, slots=True)
class DecisionResult:
    claim_status: ClaimStatus
    step_sequence: int
    new_version: int


async def _load(session: AsyncSession, claim_id: int) -> SettlementClaim:
    claim = (
        await session.execute(
            select(SettlementClaim)
            .where(SettlementClaim.id == claim_id)
            .options(selectinload(SettlementClaim.approval_steps))
        )
    ).scalar_one()
    return claim


def _current_step(claim: SettlementClaim) -> ApprovalStep:
    pending = sorted(
        (
            step
            for step in claim.approval_steps
            if not step.superseded
            and step.submission_round == claim.return_count + 1
            and step.decision is ApprovalDecision.PENDING
        ),
        key=lambda step: step.sequence,
    )
    if not pending:
        raise NoPendingStepError("This claim has no step awaiting a decision")
    return pending[0]


async def record_decision(
    session: AsyncSession,
    *,
    claim_id: int,
    expected_version: int,
    decision: ApprovalDecision,
    approver_employee_id: int | None,
    remarks: str | None = None,
) -> DecisionResult:
    """Approve, reject or return the claim's current pending step."""
    claim = await _load(session, claim_id)

    if claim.version != expected_version:
        # Refuse rather than merge. The approver was looking at a different claim to the one
        # that is now in front of them, and they should see the current state before deciding.
        raise ConcurrentModificationError(
            f"This claim has changed since you opened it (version {claim.version}, you have "
            f"{expected_version}). Reload it and review the current state before deciding."
        )

    step = _current_step(claim)
    target = _target_status(claim, step, decision)
    assert_transition(claim.status, target)

    step.decision = decision
    step.decided_at = datetime.now(UTC)
    step.remarks = remarks
    step.approver_employee_id = approver_employee_id or step.approver_employee_id

    if decision is ApprovalDecision.RETURNED:
        # §2.3: back to the employee against the same Travel Request ID. Everything approved
        # before the change stops counting - a later value must not inherit approvals given to
        # an earlier one.
        for other in claim.approval_steps:
            if other.submission_round == claim.return_count + 1:
                other.superseded = True
        claim.return_count += 1

    claim.status = target
    claim.version += 1

    session.add(
        ClaimEvent(
            claim_id=claim.id,
            travel_request_id=claim.travel_request_id,
            actor_employee_id=approver_employee_id,
            action=f"approval_{decision.value}",
            payload={
                "sequence": step.sequence,
                "role": step.role.value,
                "remarks": remarks,
                "claim_status": target.value,
            },
        )
    )

    await session.flush()
    return DecisionResult(
        claim_status=target, step_sequence=step.sequence, new_version=claim.version
    )


def _target_status(
    claim: SettlementClaim, step: ApprovalStep, decision: ApprovalDecision
) -> ClaimStatus:
    if decision is ApprovalDecision.REJECTED:
        return ClaimStatus.REJECTED
    if decision is ApprovalDecision.RETURNED:
        return ClaimStatus.DRAFT

    remaining = [
        other
        for other in claim.approval_steps
        if not other.superseded
        and other.submission_round == claim.return_count + 1
        and other.decision is ApprovalDecision.PENDING
        and other.sequence > step.sequence
    ]

    if not remaining:
        # Finance was the last step in the chain, so approving it is verification.
        return ClaimStatus.VERIFIED

    from expense_api.db.models import Role

    next_step = min(remaining, key=lambda other: other.sequence)
    return (
        ClaimStatus.PENDING_FINANCE
        if next_step.role is Role.FINANCE
        else ClaimStatus.PENDING_APPROVAL
    )
