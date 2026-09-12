"""Trips, their evidence, and the employee's own claim.

The router declares no prefix; it is mounted in create_app() so the URL map stays readable in
one place.

Every route resolves the caller first (`X-Emp-Code`, see identity/deps.py) and scopes what it
returns to them. A trip the caller has no part in is a 404, not a 403: a 403 confirms the trip
exists, which is exactly what someone probing for other people's claims is trying to learn.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from expense_api.claims import serialisers, withdrawals
from expense_api.claims.lifecycle import submission_deadline
from expense_api.claims.materialise import NotSubmittable, load_claim
from expense_api.claims.materialise import submit as materialise_submit
from expense_api.claims.pipeline import ClaimDraft, build_claim
from expense_api.claims.schemas import (
    ClaimResponse,
    EmployeeResponse,
    SubmitClaimResponse,
    TripSummaryResponse,
    UploadDocumentResponse,
    UploadedDocumentResponse,
    WithdrawLineRequest,
)
from expense_api.config.settings import settings
from expense_api.db.database import get_async_session
from expense_api.db.models import (
    ApprovalDecision,
    ApprovalStep,
    ClaimEvent,
    ClaimStatus,
    DocKind,
    Employee,
    EvidenceDocument,
    SettlementClaim,
    TravelRequest,
)
from expense_api.evidence.uploads import (
    DECLARABLE_KINDS,
    UploadRejected,
    delete_upload,
    store_upload,
)
from expense_api.identity.deps import CurrentUser, profile_for
from expense_api.notifications.service import notify_submitted

logger = logging.getLogger(__name__)

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_async_session)]


@router.get("/employees", response_model=list[EmployeeResponse], tags=["reference"])
async def list_employees(session: Session) -> list[EmployeeResponse]:
    """Everyone in the employee master. Drives the profile picker that stands in for login.

    Deliberately unauthenticated: it is the only way in, and it exposes nothing an internal
    directory would not - no claims, no amounts, no evidence.
    """
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
async def list_trips(session: Session, user: CurrentUser) -> list[TripSummaryResponse]:
    """An employee's own trips. For an approver, the trips they have been routed."""
    requests = await _visible_trips(session, user)

    out: list[TripSummaryResponse] = []
    for request in requests:
        employee = await session.get(Employee, request.employee_id)
        claim = await load_claim(session, request.id)
        status, payable, awaiting = await _summary_for(session, request, claim, user)

        out.append(
            TripSummaryResponse(
                external_id=request.external_id,
                trq_id=request.trq_id,
                employee_name=employee.name if employee else "Unknown",
                employee_code=employee.emp_code if employee else "",
                destination=request.destination_city,
                from_date=request.from_date,
                to_date=request.to_date,
                status=status,
                payable=payable,
                submission_deadline=submission_deadline(request.to_date),
                awaiting_me=awaiting,
            )
        )
    return out


@router.get("/trips/{trq_id}/claim", response_model=ClaimResponse, tags=["trips"])
async def get_claim(trq_id: str, session: Session, user: CurrentUser) -> ClaimResponse:
    """The claim as it stands.

    A draft is evaluated live from the evidence, so an uploaded bill shows up immediately. Once
    submitted, the persisted rows are served instead - an approver must see the figures that
    were submitted to them, not a recomputation that moves when anything behind it moves.
    """
    request = await _require_visible_trip(session, trq_id, user)
    claim = await load_claim(session, request.id)
    employee = await session.get(Employee, request.employee_id)

    if claim is not None and claim.status is not ClaimStatus.DRAFT:
        return serialisers.to_persisted_claim_response(
            claim,
            request=request,
            employee_name=employee.name if employee else "Unknown",
            deadline=submission_deadline(request.to_date),
            documents=await _documents(session, request.id),
            awaiting_me=_pending_step_for(claim, user) is not None,
        )

    draft = await _claim_for(session, request)
    await session.commit()

    response = serialisers.to_claim_response(
        draft,
        employee_name=employee.name if employee else "Unknown",
        deadline=submission_deadline(request.to_date),
    )
    if claim is not None:
        response.version = claim.version
        response.return_count = claim.return_count
    return response


@router.get(
    "/trips/{trq_id}/documents",
    response_model=list[UploadedDocumentResponse],
    tags=["evidence"],
)
async def list_documents(
    trq_id: str, session: Session, user: CurrentUser
) -> list[UploadedDocumentResponse]:
    """Everything attached to this trip: the mailed evidence and anything uploaded."""
    request = await _require_visible_trip(session, trq_id, user)
    return [
        UploadedDocumentResponse(
            external_id=document.external_id,
            source_filename=document.source_filename,
            doc_kind=document.doc_kind.value,
            proof_ref=document.proof_ref,
            extraction_status=document.extraction_status.value,
            needs_input_reason=document.needs_input_reason,
            uploaded=document.source_path is not None,
        )
        for document in await _documents(session, request.id)
    ]


@router.post(
    "/trips/{trq_id}/documents",
    response_model=UploadDocumentResponse,
    status_code=201,
    tags=["evidence"],
)
async def upload_document(
    trq_id: str,
    session: Session,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="A receipt image (.png/.jpg) or a mail (.eml)")],
    doc_kind: Annotated[str | None, Form(max_length=40)] = None,
    note: Annotated[str | None, Form(max_length=500)] = None,
) -> UploadDocumentResponse:
    """Add a bill to the claim.

    Only the claimant, and only while the claim is still a draft. Evidence that arrives after
    an approver has seen the claim would change what they approved, so a submitted claim has to
    be returned before it can take anything new.
    """
    request = await _require_own_draft(session, trq_id, user)

    try:
        result = await store_upload(
            session,
            travel_request=request,
            claimant=user,
            filename=file.filename or "upload",
            content=await file.read(),
            declared_kind=_declared_kind(doc_kind),
            note=note,
        )
    except UploadRejected as exc:
        raise HTTPException(
            status_code=422, detail={"code": "upload_rejected", "message": str(exc)}
        ) from exc

    await session.commit()
    document = result.document

    return UploadDocumentResponse(
        document=UploadedDocumentResponse(
            external_id=document.external_id,
            source_filename=document.source_filename,
            doc_kind=document.doc_kind.value,
            proof_ref=document.proof_ref,
            extraction_status=document.extraction_status.value,
            needs_input_reason=document.needs_input_reason,
            uploaded=True,
        ),
        message=f"Added {document.source_filename} as {document.doc_kind.value.replace('_', ' ')}.",
    )


@router.delete("/trips/{trq_id}/documents/{external_id}", status_code=204, tags=["evidence"])
async def remove_document(
    trq_id: str, external_id: str, session: Session, user: CurrentUser
) -> None:
    """Remove something the employee uploaded by mistake.

    Only their own uploads, and only while the claim is a draft. Mailed evidence from the pack
    is not removable at all: an inbox is a record of what arrived, and letting a claimant delete
    an inconvenient receipt is precisely the failure this system exists to prevent.
    """
    request = await _require_own_draft(session, trq_id, user)

    document = (
        await session.execute(
            select(EvidenceDocument).where(
                EvidenceDocument.external_id == external_id,
                EvidenceDocument.travel_request_id == request.id,
            )
        )
    ).scalar_one_or_none()

    if document is None:
        raise HTTPException(status_code=404, detail="No such document")
    if document.source_path is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_removable",
                "message": "Mailed evidence cannot be removed. Withdraw the line instead.",
            },
        )

    await delete_upload(session, document=document)
    await session.commit()


@router.post("/trips/{trq_id}/claim/withdraw", response_model=ClaimResponse, tags=["trips"])
async def withdraw_line(
    trq_id: str, payload: WithdrawLineRequest, session: Session, user: CurrentUser
) -> ClaimResponse:
    """Remove a held line from the claim so the rest can be submitted.

    Recorded, never deleted: the line stays visible with its reason, and the claim is
    re-evaluated, which can drop it into a lower approval band.
    """
    request = await _require_own_draft(session, trq_id, user)
    withdrawals.record(trq_id, payload.description)

    session.add(
        ClaimEvent(
            travel_request_id=request.id,
            actor_employee_id=user.id,
            action="line_withdrawn",
            payload={"description": payload.description, "reason": payload.reason},
        )
    )
    await session.commit()

    draft = await _claim_for(session, request)
    await session.commit()
    return serialisers.to_claim_response(
        draft,
        employee_name=user.name,
        deadline=submission_deadline(request.to_date),
    )


@router.post("/trips/{trq_id}/claim/submit", response_model=SubmitClaimResponse, tags=["trips"])
async def submit_claim(trq_id: str, session: Session, user: CurrentUser) -> SubmitClaimResponse:
    """Freeze the draft into rows, route it, and tell the first approver it is there."""
    request = await _require_own_draft(session, trq_id, user)
    draft = await _claim_for(session, request)

    try:
        await materialise_submit(session, draft=draft, claimant=user)
    except NotSubmittable as exc:
        # 422 with the reasons, not a bare 400: the client renders these next to the lines.
        raise HTTPException(
            status_code=422, detail={"code": "claim_incomplete", "message": str(exc)}
        ) from exc

    # Re-read so the approval steps and their approvers are eagerly loaded: the notification
    # names the approver, and a lazy load here would be a query from an unawaitable place.
    routed = await load_claim(session, request.id)
    if routed is None:  # pragma: no cover - it was written in this transaction
        raise RuntimeError(f"Claim for {request.trq_id} vanished immediately after submission")
    first = _pending_steps(routed)

    await notify_submitted(
        session,
        claim=routed,
        trq_id=request.trq_id,
        claimant=user,
        first_step=first[0] if first else None,
        payable=draft.summary.payable,
    )
    await session.commit()

    next_approver = first[0].approver.name if first and first[0].approver else None
    return SubmitClaimResponse(
        trq_id=request.trq_id,
        status=routed.status.value,
        claim_external_id=routed.external_id,
        version=routed.version,
        payable=f"{routed.payable:.2f}",
        next_approver=next_approver,
        chain=serialisers.to_persisted_chain(routed),
    )


# --------------------------------------------------------------------------- helpers


def _declared_kind(raw: str | None) -> DocKind | None:
    if not raw:
        return None
    try:
        kind = DocKind(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unknown_document_kind",
                "message": f"{raw!r} is not a document kind this system reads.",
            },
        ) from exc

    if kind not in DECLARABLE_KINDS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unsupported_document_kind",
                "message": f"{kind.value} cannot be read from an uploaded file.",
            },
        )
    return kind


async def _documents(session: AsyncSession, travel_request_id: int) -> list[EvidenceDocument]:
    return list(
        (
            await session.execute(
                select(EvidenceDocument)
                .where(EvidenceDocument.travel_request_id == travel_request_id)
                .order_by(EvidenceDocument.source_filename)
            )
        )
        .scalars()
        .all()
    )


def _pending_steps(claim: SettlementClaim) -> list[ApprovalStep]:
    return [
        step
        for step in serialisers.current_round_steps(claim)
        if step.decision is ApprovalDecision.PENDING
    ]


def _pending_step_for(claim: SettlementClaim, user: Employee) -> ApprovalStep | None:
    """The step this person is currently being asked to decide, if any."""
    pending = _pending_steps(claim)
    if not pending:
        return None
    return pending[0] if pending[0].approver_employee_id == user.id else None


async def _visible_trips(session: AsyncSession, user: Employee) -> list[TravelRequest]:
    if profile_for(user.role) == "employee":
        statement = select(TravelRequest).where(TravelRequest.employee_id == user.id)
    else:
        # An approver sees a trip once a claim for it has been routed to them - not before.
        # A draft belongs to its author until they submit it.
        statement = (
            select(TravelRequest)
            .join(SettlementClaim, SettlementClaim.travel_request_id == TravelRequest.id)
            .join(ApprovalStep, ApprovalStep.claim_id == SettlementClaim.id)
            .where(ApprovalStep.approver_employee_id == user.id)
            .distinct()
        )

    return list(
        (await session.execute(statement.order_by(TravelRequest.from_date.desc()))).scalars().all()
    )


async def _summary_for(
    session: AsyncSession,
    request: TravelRequest,
    claim: SettlementClaim | None,
    user: Employee,
) -> tuple[str, str, bool]:
    """Status, payable and "is it on my desk" for the trip list.

    A submitted claim answers from its own row. A draft has to be evaluated, which is the
    expensive path - it re-reads every document - so it only runs when there is no claim yet.
    """
    if claim is not None and claim.status is not ClaimStatus.DRAFT:
        return (
            claim.status.value,
            f"{claim.payable:.2f}",
            _pending_step_for(claim, user) is not None,
        )

    draft = await _claim_for(session, request)
    await session.commit()
    status = "ready_to_submit" if draft.can_submit else "draft"
    return status, f"{draft.summary.payable:.2f}", False


async def _require_visible_trip(
    session: AsyncSession, trq_id: str, user: Employee
) -> TravelRequest:
    request = (
        await session.execute(
            select(TravelRequest)
            .where(TravelRequest.trq_id == trq_id)
            .options(selectinload(TravelRequest.employee))
        )
    ).scalar_one_or_none()

    # 404 rather than 403 for anything the caller may not see: a 403 confirms it exists.
    if request is None:
        raise HTTPException(status_code=404, detail="No such trip")
    if request.employee_id == user.id:
        return request

    if profile_for(user.role) == "admin":
        routed = (
            await session.execute(
                select(ApprovalStep.id)
                .join(SettlementClaim, SettlementClaim.id == ApprovalStep.claim_id)
                .where(
                    SettlementClaim.travel_request_id == request.id,
                    ApprovalStep.approver_employee_id == user.id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if routed is not None:
            return request

    raise HTTPException(status_code=404, detail="No such trip")


async def _require_own_draft(session: AsyncSession, trq_id: str, user: Employee) -> TravelRequest:
    """The claimant's own trip, with its claim still editable."""
    request = await _require_visible_trip(session, trq_id, user)

    if request.employee_id != user.id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "not_the_claimant",
                "message": "Only the person who travelled can change this claim.",
            },
        )

    claim = await load_claim(session, request.id)
    if claim is not None and claim.status is not ClaimStatus.DRAFT:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "claim_locked",
                "message": (
                    f"This claim is {claim.status.value.replace('_', ' ')} and cannot be "
                    "changed. An approver has to return it first."
                ),
            },
        )
    return request


async def _claim_for(session: AsyncSession, request: TravelRequest) -> ClaimDraft:
    return await build_claim(
        session,
        travel_request=request,
        emails_dir=settings.pack_dir / "sample_emails",
        receipts_dir=settings.pack_dir / "receipts",
        withdrawn_descriptions=withdrawals.for_trip(request.trq_id),
    )
