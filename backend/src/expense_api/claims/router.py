"""Trips and their claims.

The router declares no prefix; it is mounted in create_app() so the URL map stays readable in
one place.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.claims import serialisers
from expense_api.claims.lifecycle import submission_deadline
from expense_api.claims.pipeline import build_claim
from expense_api.claims.schemas import (
    ClaimResponse,
    EmployeeResponse,
    SubmitClaimResponse,
    TripSummaryResponse,
    WithdrawLineRequest,
)
from expense_api.config.settings import settings
from expense_api.db.database import get_async_session
from expense_api.db.models import ClaimEvent, Employee, TravelRequest

logger = logging.getLogger(__name__)

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_async_session)]

# Withdrawals are per-process state for this build. Persisting them belongs with the
# SettlementClaim row; keeping it here keeps the demo honest about what is and is not stored.
_WITHDRAWN: dict[str, set[str]] = {}


@router.get("/employees", response_model=list[EmployeeResponse], tags=["reference"])
async def list_employees(session: Session) -> list[EmployeeResponse]:
    """Everyone in the employee master. Drives the role switcher that stands in for login."""
    people = (await session.execute(select(Employee).order_by(Employee.emp_code))).scalars().all()
    return [
        EmployeeResponse(
            emp_code=person.emp_code,
            name=person.name,
            role=person.role.value,
            designation=person.designation,
        )
        for person in people
    ]


@router.get("/trips", response_model=list[TripSummaryResponse], tags=["trips"])
async def list_trips(session: Session) -> list[TripSummaryResponse]:
    requests = (
        (await session.execute(select(TravelRequest).order_by(TravelRequest.from_date.desc())))
        .scalars()
        .all()
    )

    out: list[TripSummaryResponse] = []
    for request in requests:
        employee = await session.get(Employee, request.employee_id)
        claim = await _claim_for(session, request)
        out.append(
            TripSummaryResponse(
                external_id=request.external_id,
                trq_id=request.trq_id,
                employee_name=employee.name if employee else "Unknown",
                destination=request.destination_city,
                from_date=request.from_date,
                to_date=request.to_date,
                status="Draft" if not claim.can_submit else "Ready to submit",
                payable=f"{claim.summary.payable:.2f}",
            )
        )
    return out


@router.get("/trips/{trq_id}/claim", response_model=ClaimResponse, tags=["trips"])
async def get_claim(trq_id: str, session: Session) -> ClaimResponse:
    request = await _require_trip(session, trq_id)
    claim = await _claim_for(session, request)
    employee = await session.get(Employee, request.employee_id)

    return serialisers.to_claim_response(
        claim,
        employee_name=employee.name if employee else "Unknown",
        deadline=submission_deadline(request.to_date),
    )


@router.post("/trips/{trq_id}/claim/withdraw", response_model=ClaimResponse, tags=["trips"])
async def withdraw_line(
    trq_id: str, payload: WithdrawLineRequest, session: Session
) -> ClaimResponse:
    """Remove a held line from the claim so the rest can be submitted.

    Recorded, never deleted: the line stays visible with its reason, and the claim is
    re-evaluated, which can drop it into a lower approval band.
    """
    request = await _require_trip(session, trq_id)
    _WITHDRAWN.setdefault(trq_id, set()).add(payload.description)

    session.add(
        ClaimEvent(
            travel_request_id=request.id,
            action="line_withdrawn",
            payload={"description": payload.description, "reason": payload.reason},
        )
    )
    await session.commit()

    claim = await _claim_for(session, request)
    employee = await session.get(Employee, request.employee_id)
    return serialisers.to_claim_response(
        claim,
        employee_name=employee.name if employee else "Unknown",
        deadline=submission_deadline(request.to_date),
    )


@router.post("/trips/{trq_id}/claim/submit", response_model=SubmitClaimResponse, tags=["trips"])
async def submit_claim(trq_id: str, session: Session) -> SubmitClaimResponse:
    request = await _require_trip(session, trq_id)
    claim = await _claim_for(session, request)

    if not claim.can_submit:
        # 422 with the reasons, not a bare 400: the client renders these next to the lines.
        raise HTTPException(
            status_code=422,
            detail={"code": "claim_incomplete", "message": "; ".join(claim.blocking_reasons)},
        )

    session.add(
        ClaimEvent(
            travel_request_id=request.id,
            action="claim_submitted",
            payload={
                "net_reimbursable": f"{claim.summary.net_reimbursable:.2f}",
                "chain": [step.role.value for step in claim.chain],
            },
        )
    )
    await session.commit()

    return SubmitClaimResponse(
        trq_id=request.trq_id,
        status="pending_approval",
        chain=serialisers.to_chain(claim.chain),
    )


async def _require_trip(session: AsyncSession, trq_id: str) -> TravelRequest:
    request = (
        await session.execute(select(TravelRequest).where(TravelRequest.trq_id == trq_id))
    ).scalar_one_or_none()

    if request is None:
        # 404 rather than 403 for anything the caller may not see: a 403 confirms it exists.
        raise HTTPException(status_code=404, detail="No such trip")
    return request


async def _claim_for(session: AsyncSession, request: TravelRequest):  # type: ignore[no-untyped-def]
    return await build_claim(
        session,
        travel_request=request,
        emails_dir=settings.pack_dir / "sample_emails",
        receipts_dir=settings.pack_dir / "receipts",
        withdrawn_descriptions=frozenset(_WITHDRAWN.get(request.trq_id, set())),
    )
