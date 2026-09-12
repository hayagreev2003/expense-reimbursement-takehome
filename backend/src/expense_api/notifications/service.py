"""Writing notifications.

The rule the rest of the application relies on: **a claim never changes hands silently.** Every
transition writes to the person who now has to act and to the person who was waiting on it. The
two messages are separate rows, because the wording differs and so does the read state - the
employee marking theirs read must not clear the approver's.

Notifications are written in the same transaction as the state change they describe. A commit
that moved a claim but lost its notification would leave a claim sitting in someone's queue
with nothing telling them it is there, which is exactly the follow-up problem this system
exists to remove.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.db.models import (
    ApprovalDecision,
    ApprovalStep,
    ClaimStatus,
    Employee,
    Notification,
    NotificationKind,
    SettlementClaim,
)

logger = logging.getLogger(__name__)


def _money(value: Decimal) -> str:
    return f"INR {value:,.2f}"


async def notify(
    session: AsyncSession,
    *,
    recipient_id: int,
    kind: NotificationKind,
    title: str,
    body: str,
    trq_id: str | None = None,
    claim_id: int | None = None,
    travel_request_id: int | None = None,
    actor_id: int | None = None,
) -> Notification:
    row = Notification(
        recipient_employee_id=recipient_id,
        kind=kind,
        title=title,
        body=body,
        trq_id=trq_id,
        claim_id=claim_id,
        travel_request_id=travel_request_id,
        actor_employee_id=actor_id,
    )
    session.add(row)
    return row


async def unread_count(session: AsyncSession, *, recipient_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.recipient_employee_id == recipient_id,
                    Notification.read_at.is_(None),
                )
            )
        ).scalar_one()
    )


async def notify_submitted(
    session: AsyncSession,
    *,
    claim: SettlementClaim,
    trq_id: str,
    claimant: Employee,
    first_step: ApprovalStep | None,
    payable: Decimal,
) -> None:
    """Employee submitted. Tell them it went, and tell the first approver it arrived."""
    await notify(
        session,
        recipient_id=claimant.id,
        kind=NotificationKind.CLAIM_SUBMITTED,
        title=f"{trq_id} submitted for approval",
        body=(
            f"Your settlement claim for {trq_id} was submitted. "
            f"{_money(payable)} is claimed. "
            + (
                f"It is now with {first_step.approver.name} ({first_step.role.value})."
                if first_step and first_step.approver
                else "It is now in the approval queue."
            )
        ),
        trq_id=trq_id,
        claim_id=claim.id,
        travel_request_id=claim.travel_request_id,
        actor_id=claimant.id,
    )

    if first_step and first_step.approver_employee_id:
        await notify(
            session,
            recipient_id=first_step.approver_employee_id,
            kind=NotificationKind.AWAITING_YOUR_APPROVAL,
            title=f"{trq_id} needs your approval",
            body=(
                f"{claimant.name} submitted a settlement claim of {_money(payable)} for {trq_id}. "
                f"You are step {first_step.sequence} ({first_step.role.value})."
            ),
            trq_id=trq_id,
            claim_id=claim.id,
            travel_request_id=claim.travel_request_id,
            actor_id=claimant.id,
        )


_DECISION_VERB = {
    ApprovalDecision.APPROVED: "approved",
    ApprovalDecision.REJECTED: "rejected",
    ApprovalDecision.RETURNED: "returned",
}


async def notify_decided(
    session: AsyncSession,
    *,
    claim: SettlementClaim,
    trq_id: str,
    claimant: Employee,
    actor: Employee,
    decision: ApprovalDecision,
    remarks: str | None,
    next_step: ApprovalStep | None,
) -> None:
    """An approver acted. The employee always hears about it; the next approver inherits it."""
    verb = _DECISION_VERB[decision]
    remark_text = f' Remarks: "{remarks}"' if remarks else ""

    if decision is ApprovalDecision.APPROVED and claim.status is ClaimStatus.VERIFIED:
        kind, tail = NotificationKind.CLAIM_VERIFIED, " Finance has verified it for payment."
    elif decision is ApprovalDecision.APPROVED:
        kind = NotificationKind.CLAIM_APPROVED
        tail = (
            f" It has moved to {next_step.approver.name} ({next_step.role.value})."
            if next_step and next_step.approver
            else " It has moved to the next approver."
        )
    elif decision is ApprovalDecision.RETURNED:
        kind = NotificationKind.CLAIM_RETURNED
        tail = " Correct it and resubmit against the same Travel Request ID."
    else:
        kind, tail = NotificationKind.CLAIM_REJECTED, ""

    await notify(
        session,
        recipient_id=claimant.id,
        kind=kind,
        title=f"{trq_id} {verb} by {actor.name}",
        body=(
            f"{actor.name} ({actor.designation}) {verb} your claim for {trq_id}.{remark_text}{tail}"
        ),
        trq_id=trq_id,
        claim_id=claim.id,
        travel_request_id=claim.travel_request_id,
        actor_id=actor.id,
    )

    if (
        decision is ApprovalDecision.APPROVED
        and next_step is not None
        and next_step.approver_employee_id
    ):
        await notify(
            session,
            recipient_id=next_step.approver_employee_id,
            kind=NotificationKind.AWAITING_YOUR_APPROVAL,
            title=f"{trq_id} needs your approval",
            body=(
                f"{actor.name} approved {claimant.name}'s claim for {trq_id}. "
                f"It is now with you as step {next_step.sequence} ({next_step.role.value})."
            ),
            trq_id=trq_id,
            claim_id=claim.id,
            travel_request_id=claim.travel_request_id,
            actor_id=actor.id,
        )
