"""Response models for the claim review surface.

Naming follows <Verb><Noun>Request / <Verb><Noun>Response, one model per direction. Timestamps
and dates serialise as explicit ISO strings with a UTC marker where they carry a time, because
a naive datetime gets reparsed in the browser's local timezone and the status timeline silently
shifts by hours.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class Money(BaseModel):
    """Amounts cross the wire as strings so no float ever touches them in JavaScript."""

    model_config = ConfigDict(frozen=True)

    amount: str
    currency: str = "INR"

    @classmethod
    def of(cls, value: Decimal) -> Money:
        return cls(amount=f"{value:.2f}")


class PolicyDecisionResponse(BaseModel):
    rule_id: str
    outcome: str
    reason: str
    citation: str
    amount_effect: str


class ClaimLineResponse(BaseModel):
    index: int
    head: str
    description: str
    line_date: date | None
    paid_by: Literal["Employee", "Company"]
    gross_amount: str
    tax_share: str
    allowed_amount: str
    disallowed_amount: str
    status: str
    proof_ref: str | None
    nights: int | None
    decisions: list[PolicyDecisionResponse]


class SettlementSummaryResponse(BaseModel):
    employee_paid_gross: str
    company_paid_memo: str
    disallowed_total: str
    net_reimbursable: str
    advance_drawn: str
    payable: str
    recoverable: str


class ApprovalStepResponse(BaseModel):
    sequence: int
    role: str
    approver_name: str | None
    approver_code: str | None
    note: str | None
    decision: str = "pending"
    decided_at: datetime | None = None
    remarks: str | None = None

    @field_serializer("decided_at")
    def _utc(self, value: datetime | None) -> str | None:
        """Explicit Z. A naive timestamp is reparsed as local time in the browser."""
        return value.isoformat().replace("+00:00", "Z") if value else None


class SetAsideDocumentResponse(BaseModel):
    """Seen and deliberately not claimed. Shown so nothing looks like it was missed."""

    source_filename: str
    reason: str


class SuppressedDuplicateResponse(BaseModel):
    reason: str
    strength: str


class ClaimResponse(BaseModel):
    trq_id: str
    employee_name: str
    destination: str
    city_class: str
    from_date: date
    to_date: date
    status: str
    submission_deadline: date
    lines: list[ClaimLineResponse]
    summary: SettlementSummaryResponse
    chain: list[ApprovalStepResponse]
    can_submit: bool
    blocking_reasons: list[str]
    coverage_gaps: list[date]
    set_aside: list[SetAsideDocumentResponse]
    suppressed_duplicates: list[SuppressedDuplicateResponse]
    needs_input: list[SetAsideDocumentResponse]

    # Present once the claim has been submitted and written down. `version` is the optimistic
    # lock an approver's decision is pinned to; sending a decision without it would let two
    # approvers act on the same step.
    version: int | None = None
    submitted_at: datetime | None = None
    return_count: int = 0
    # True when these lines come from the persisted claim rather than a live evaluation of the
    # evidence. An approver always sees a frozen claim: what they sign off on cannot change
    # underneath them because the employee uploaded another bill.
    frozen: bool = False
    # Whether the person asking is the approver this claim is currently waiting on.
    awaiting_me: bool = False

    @field_serializer("submitted_at")
    def _submitted_utc(self, value: datetime | None) -> str | None:
        return value.isoformat().replace("+00:00", "Z") if value else None


class TripSummaryResponse(BaseModel):
    external_id: str
    trq_id: str
    employee_name: str
    employee_code: str
    destination: str
    from_date: date
    to_date: date
    status: str
    payable: str
    submission_deadline: date
    awaiting_me: bool = False


class EmployeeResponse(BaseModel):
    external_id: str | None = None
    emp_code: str
    name: str
    role: str
    designation: str


class ApprovalQueueItemResponse(BaseModel):
    """One claim waiting on the signed-in approver."""

    trq_id: str
    claim_external_id: str
    employee_name: str
    employee_code: str
    destination: str
    from_date: date
    to_date: date
    status: str
    payable: str
    net_reimbursable: str
    disallowed_total: str
    version: int
    sequence: int
    role: str
    decision: str
    submitted_at: datetime | None
    remarks: str | None = None

    @field_serializer("submitted_at")
    def _utc(self, value: datetime | None) -> str | None:
        return value.isoformat().replace("+00:00", "Z") if value else None


class UploadedDocumentResponse(BaseModel):
    external_id: str
    source_filename: str
    doc_kind: str
    proof_ref: str
    extraction_status: str
    needs_input_reason: str | None
    uploaded: bool


class UploadDocumentResponse(BaseModel):
    document: UploadedDocumentResponse
    message: str


class WithdrawLineRequest(BaseModel):
    description: str = Field(max_length=300)
    reason: str = Field(default="Withdrawn by the employee.", max_length=500)


class SubmitClaimResponse(BaseModel):
    trq_id: str
    status: str
    claim_external_id: str
    version: int
    payable: str
    next_approver: str | None
    chain: list[ApprovalStepResponse]


class RecordDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "returned"]
    approver_code: str = Field(max_length=16)
    expected_version: int
    remarks: str | None = Field(default=None, max_length=1000)


class RecordDecisionResponse(BaseModel):
    trq_id: str
    claim_status: str
    step_sequence: int
    new_version: int
