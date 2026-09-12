"""Unit 7, database half: transitions and contention that only the database can decide."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.approvals.service import (
    ConcurrentModificationError,
    NoPendingStepError,
    record_decision,
)
from expense_api.db.models import (
    ApprovalDecision,
    ApprovalStep,
    ClaimEvent,
    ClaimStatus,
    Role,
    SettlementClaim,
)
from tests.db_helpers import make_employee, make_policy_version, make_travel_request

pytestmark = [pytest.mark.db, pytest.mark.asyncio]


async def _claim_with_chain(session: AsyncSession) -> SettlementClaim:
    """The sample claim's chain: Reporting Manager, Head of Department, Finance."""
    manager = await make_employee(session, emp_code="NX-2210", role=Role.REPORTING_MANAGER)
    hod = await make_employee(session, emp_code="NX-1108", role=Role.HEAD_OF_DEPARTMENT)
    finance = await make_employee(session, emp_code="NX-3300", role=Role.FINANCE)
    employee = await make_employee(session, emp_code="NX-4471", reporting_manager_code="NX-2210")

    request = await make_travel_request(session, employee=employee)
    version = await make_policy_version(session)
    claim = SettlementClaim(
        travel_request_id=request.id,
        policy_version_id=version.id,
        status=ClaimStatus.PENDING_APPROVAL,
        net_reimbursable=Decimal("26388.44"),
        payable=Decimal("6388.44"),
    )
    session.add(claim)
    await session.flush()

    for sequence, (role, person) in enumerate(
        [
            (Role.REPORTING_MANAGER, manager),
            (Role.HEAD_OF_DEPARTMENT, hod),
            (Role.FINANCE, finance),
        ],
        start=1,
    ):
        session.add(
            ApprovalStep(
                claim_id=claim.id,
                sequence=sequence,
                role=role,
                approver_employee_id=person.id,
            )
        )
    await session.flush()
    return claim


async def test_the_chain_advances_one_level_at_a_time(db_session: AsyncSession) -> None:
    claim = await _claim_with_chain(db_session)

    first = await record_decision(
        db_session,
        claim_id=claim.id,
        expected_version=claim.version,
        decision=ApprovalDecision.APPROVED,
        approver_employee_id=None,
    )
    assert first.claim_status is ClaimStatus.PENDING_APPROVAL
    assert first.step_sequence == 1

    second = await record_decision(
        db_session,
        claim_id=claim.id,
        expected_version=first.new_version,
        decision=ApprovalDecision.APPROVED,
        approver_employee_id=None,
    )
    # Head of Department approved, so Finance is next - a distinct state, per §2.1.
    assert second.claim_status is ClaimStatus.PENDING_FINANCE

    third = await record_decision(
        db_session,
        claim_id=claim.id,
        expected_version=second.new_version,
        decision=ApprovalDecision.APPROVED,
        approver_employee_id=None,
    )
    assert third.claim_status is ClaimStatus.VERIFIED


async def test_a_stale_version_is_refused(db_session: AsyncSession) -> None:
    """Two approvers both opened the claim; the second must not act on what they saw."""
    claim = await _claim_with_chain(db_session)
    stale_version = claim.version

    await record_decision(
        db_session,
        claim_id=claim.id,
        expected_version=stale_version,
        decision=ApprovalDecision.APPROVED,
        approver_employee_id=None,
    )

    with pytest.raises(ConcurrentModificationError, match="changed since you opened it"):
        await record_decision(
            db_session,
            claim_id=claim.id,
            expected_version=stale_version,
            decision=ApprovalDecision.REJECTED,
            approver_employee_id=None,
        )


async def test_only_one_decision_lands_per_step(db_session: AsyncSession) -> None:
    """The guarantee the version check exists for, stated as an outcome."""
    claim = await _claim_with_chain(db_session)
    version = claim.version

    await record_decision(
        db_session,
        claim_id=claim.id,
        expected_version=version,
        decision=ApprovalDecision.APPROVED,
        approver_employee_id=None,
    )
    with pytest.raises(ConcurrentModificationError):
        await record_decision(
            db_session,
            claim_id=claim.id,
            expected_version=version,
            decision=ApprovalDecision.APPROVED,
            approver_employee_id=None,
        )

    decided = (
        (
            await db_session.execute(
                select(ApprovalStep).where(
                    ApprovalStep.claim_id == claim.id,
                    ApprovalStep.decision != ApprovalDecision.PENDING,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(decided) == 1


async def test_returning_supersedes_the_whole_round(db_session: AsyncSession) -> None:
    """§2.3. A later value must not inherit approvals given to an earlier one."""
    claim = await _claim_with_chain(db_session)

    approved = await record_decision(
        db_session,
        claim_id=claim.id,
        expected_version=claim.version,
        decision=ApprovalDecision.APPROVED,
        approver_employee_id=None,
    )
    returned = await record_decision(
        db_session,
        claim_id=claim.id,
        expected_version=approved.new_version,
        decision=ApprovalDecision.RETURNED,
        approver_employee_id=None,
        remarks="Please attach the attendee names for the dinner.",
    )

    assert returned.claim_status is ClaimStatus.DRAFT

    steps = (
        (await db_session.execute(select(ApprovalStep).where(ApprovalStep.claim_id == claim.id)))
        .scalars()
        .all()
    )
    assert all(step.superseded for step in steps)
    # History is kept, not deleted: who approved what value survives the return.
    assert any(step.decision is ApprovalDecision.APPROVED for step in steps)

    await db_session.refresh(claim)
    assert claim.return_count == 1


async def test_a_returned_claim_has_no_pending_step_until_resubmission(
    db_session: AsyncSession,
) -> None:
    claim = await _claim_with_chain(db_session)
    result = await record_decision(
        db_session,
        claim_id=claim.id,
        expected_version=claim.version,
        decision=ApprovalDecision.RETURNED,
        approver_employee_id=None,
        remarks="Missing attendee names.",
    )

    with pytest.raises(NoPendingStepError):
        await record_decision(
            db_session,
            claim_id=claim.id,
            expected_version=result.new_version,
            decision=ApprovalDecision.APPROVED,
            approver_employee_id=None,
        )


async def test_rejection_is_terminal(db_session: AsyncSession) -> None:
    claim = await _claim_with_chain(db_session)

    result = await record_decision(
        db_session,
        claim_id=claim.id,
        expected_version=claim.version,
        decision=ApprovalDecision.REJECTED,
        approver_employee_id=None,
        remarks="Not a business expense.",
    )

    assert result.claim_status is ClaimStatus.REJECTED


async def test_every_decision_is_written_to_the_audit_trail(db_session: AsyncSession) -> None:
    claim = await _claim_with_chain(db_session)

    await record_decision(
        db_session,
        claim_id=claim.id,
        expected_version=claim.version,
        decision=ApprovalDecision.APPROVED,
        approver_employee_id=None,
        remarks="Fine by me.",
    )

    events = (
        (await db_session.execute(select(ClaimEvent).where(ClaimEvent.claim_id == claim.id)))
        .scalars()
        .all()
    )

    assert len(events) == 1
    assert events[0].action == "approval_approved"
    assert events[0].payload["role"] == "Reporting Manager"
    assert events[0].payload["remarks"] == "Fine by me."
