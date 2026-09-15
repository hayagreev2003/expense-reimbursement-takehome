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

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from expense_api.db.models import CityClass


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
    # Documents whose figures the claimant typed in. An approver signing a claim is entitled to
    # know which of its numbers came off a bill and which came off a keyboard. Required rather
    # than defaulted: a default makes it optional in the generated client, and the browser then
    # has to guard a list the server always sends.
    manually_entered: list[SetAsideDocumentResponse]

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


class CreateTripRequest(BaseModel):
    """Apply for a new trip, which is what a settlement claim is later filed against.

    One model for this direction only; the trip is read back as TripSummaryResponse.
    `travel_category` defaults to "Domestic - <city class>" when omitted, matching the
    seeded trip's form. An advance named here is a *request*, not money disbursed -
    Finance disburses separately and only disbursed advances settle against the claim.
    """

    destination_city: str = Field(min_length=2, max_length=80)
    from_date: date
    to_date: date
    purpose: str = Field(min_length=4, max_length=300)
    city_class: CityClass
    mode_of_travel: Literal["Flight", "Train", "Bus", "Cab", "Self-drive"] = "Flight"
    visiting_company: str | None = Field(default=None, max_length=160)
    travel_category: str | None = Field(default=None, max_length=60)
    advance_requested: Decimal | None = Field(default=None, ge=Decimal("0.00"))

    @model_validator(mode="after")
    def _dates_ordered(self) -> CreateTripRequest:
        if self.to_date < self.from_date:
            raise ValueError("The trip cannot end before it begins.")
        return self


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
    # Figures typed in by the claimant because nothing could read the document.
    manually_entered: bool = False
    # Whether this document will accept a correction. False for anything that was read and
    # reconciled, and for every document once the claim has left draft.
    correctable: bool = False


class UploadDocumentResponse(BaseModel):
    document: UploadedDocumentResponse
    message: str


class CorrectedLineRequest(BaseModel):
    """One line as the claimant reads it off a bill nothing could read for them.

    `paid_by` is asked rather than inferred. On a read bill the payment method is printed on it;
    here there is nothing to read, and a line silently defaulted to Company drops out of the
    reimbursable total - the more damaging direction to be wrong in.
    """

    description: str = Field(min_length=2, max_length=300)
    gross_amount: Decimal = Field(gt=Decimal("0.00"), max_digits=12, decimal_places=2)
    txn_date: date
    merchant: str | None = Field(default=None, max_length=200)
    bill_no: str | None = Field(default=None, max_length=60)
    # A component of the gross above, not an addition to it.
    tax_amount: Decimal | None = Field(default=None, ge=Decimal("0.00"), max_digits=12)
    # Lodging only. §3.1 is a per-night limit, so a folio without this is measured against one
    # night's tariff and most of it disallowed.
    nights: int | None = Field(default=None, ge=1, le=120)
    paid_by: Literal["Employee", "Company"] = "Employee"

    @model_validator(mode="after")
    def _tax_is_within_the_gross(self) -> CorrectedLineRequest:
        if self.tax_amount is not None and self.tax_amount > self.gross_amount:
            raise ValueError("The tax on a line cannot exceed the line itself.")
        return self


class CorrectDocumentRequest(BaseModel):
    """What a bill says, entered by hand, when extraction could not say it.

    `stated_total` is optional and is a guard, not data: give the total printed on the bill and
    the lines must add up to it. That is the same discipline the reconciliation check applies to
    a read document, and it is the only thing standing between a typo and a claim line.
    """

    lines: list[CorrectedLineRequest] = Field(min_length=1, max_length=40)
    stated_total: Decimal | None = Field(default=None, gt=Decimal("0.00"), max_digits=12)

    def total_mismatch(self) -> str | None:
        """Why these lines do not match the total on the bill, if they do not.

        Checked here but raised by the router, deliberately. A Pydantic validation error comes
        back as an array that echoes the submitted values, so the client cannot show it and
        falls back to "some details need correcting" - which hides the one number the claimant
        needs to see. The router raises it as `{code, message}`, which is renderable.
        """
        if self.stated_total is None:
            return None

        entered = sum((line.gross_amount for line in self.lines), Decimal("0.00"))
        if entered == self.stated_total:
            return None

        return (
            f"The lines add up to {entered:.2f}, not the {self.stated_total:.2f} stated on the "
            f"bill. Correct the lines or the total."
        )


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
