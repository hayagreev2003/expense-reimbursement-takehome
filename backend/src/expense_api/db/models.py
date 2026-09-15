"""SQLAlchemy models.

Everything hangs off a Travel Request ID. Policy §1.1: "Every downstream artefact - bookings,
bills, the settlement claim, the payment - is tracked against that ID." Nothing in this schema
exists outside one.

Conventions:

- Integer primary keys stay server-side. Anything a client can name carries an `external_id`
  UUID instead, so an employee cannot enumerate another employee's claims by counting.
- Money is `Money` (integer paise, surfaced as Decimal). Never Float, never Numeric - see
  db/types.py for why.
- Constrained values use `sa.Enum(..., native_enum=False)`, which renders as VARCHAR plus a
  CHECK constraint on SQLite. A bad value is rejected by the database, not only by Pydantic.
- JSON columns are `sa.JSON`, not JSONB. Portability is deliberate; nothing here needs JSONB
  operators.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from expense_api.db.types import Money


class Base(DeclarativeBase):
    pass


def _external_id() -> str:
    return str(uuid4())


def _enum(enum_cls: type[enum.StrEnum], length: int) -> Enum:
    """Persist the enum's *value*, not its member name.

    SQLAlchemy's default stores `Role.REPORTING_MANAGER` as "REPORTING_MANAGER". The policy
    document - and therefore the approval matrix in policy/versions/*.yaml - says
    "Reporting Manager". Storing names would leave the CHECK constraint, the rows, and the
    policy permanently out of step, and every raw SQL query would need a translation table.
    """
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda e: [member.value for member in e],
        # Not the default. Since SQLAlchemy 1.4 `create_constraint` is False, so
        # native_enum=False on its own yields a plain VARCHAR with nothing checking it - and a
        # claim that "the database rejects bad values" that happens to be untrue.
        create_constraint=True,
    )


class ExternalIdMixin:
    """Opaque public identifier. Integer PKs never leave the server."""

    external_id: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, default=_external_id
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- enums


class Role(enum.StrEnum):
    EMPLOYEE = "Employee"
    REPORTING_MANAGER = "Reporting Manager"
    HEAD_OF_DEPARTMENT = "Head of Department"
    HEAD_OF_DIVISION = "Head of Division"
    MD = "MD"
    FINANCE = "Finance"


class CityClass(enum.StrEnum):
    TIER_1 = "Tier 1"
    TIER_2 = "Tier 2"
    TIER_3 = "Tier 3"


class BorneBy(enum.StrEnum):
    """Policy §3 splits estimates by who bears the cost."""

    COMPANY = "Company"
    EMPLOYEE = "Employee"


class PaidBy(enum.StrEnum):
    """The settlement form's SUMIF keys on this exact word (template legend line 63).

    Derived from payment evidence, never from the travel request's plan - the sample trip's
    hotel was budgeted Company and settled on the employee's personal card.
    """

    COMPANY = "Company"
    EMPLOYEE = "Employee"


class ExpenseHead(enum.StrEnum):
    LODGING = "Lodging"
    TRANSPORT = "Travel & Transportation"
    MEALS = "Meals"
    BUSINESS_ENTERTAINMENT = "Business Entertainment"
    MISC = "Misc"


class DocKind(enum.StrEnum):
    """Assigned before extraction. The last two never produce a claim line."""

    APPROVAL_REQUEST = "approval_request"
    APPROVAL_GRANT = "approval_grant"
    ADVANCE_NOTICE = "advance_notice"
    FLIGHT_BOOKING = "flight_booking"
    HOTEL_VOUCHER = "hotel_voucher"
    HOTEL_INVOICE = "hotel_invoice"
    CAB_RECEIPT = "cab_receipt"
    RESTAURANT_BILL = "restaurant_bill"
    THIRD_PARTY_FORWARD = "third_party_forward"
    CAB_PAYMENT_FAILURE = "cab_payment_failure"
    PROMOTIONAL = "promotional"
    UNKNOWN = "unknown"


class ExtractionStatus(enum.StrEnum):
    PENDING = "pending"
    EXTRACTED = "extracted"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class ClaimLineStatus(enum.StrEnum):
    """`held` blocks submission; `withdrawn` is the employee's explicit escape from that.

    Nothing is ever deleted - template legend line 66: disallowed items go on the disallowed
    row with a remark, they are not silently dropped.
    """

    ALLOWED = "allowed"
    DISALLOWED = "disallowed"
    HELD = "held"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    MEMO = "memo"


class ClaimStatus(enum.StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    PENDING_FINANCE = "pending_finance"
    VERIFIED = "verified"
    SCHEDULED_FOR_PAYMENT = "scheduled_for_payment"
    PAID = "paid"
    REJECTED = "rejected"


class NotificationKind(enum.StrEnum):
    """What happened. The recipient is stored separately - the same event notifies two people
    with different wording (the employee is told their claim moved; the next approver is told
    something is waiting)."""

    CLAIM_SUBMITTED = "claim_submitted"
    AWAITING_YOUR_APPROVAL = "awaiting_your_approval"
    CLAIM_APPROVED = "claim_approved"
    CLAIM_RETURNED = "claim_returned"
    CLAIM_REJECTED = "claim_rejected"
    CLAIM_VERIFIED = "claim_verified"


class ApprovalDecision(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETURNED = "returned"


class DecisionOutcome(enum.StrEnum):
    ALLOWED = "allowed"
    DISALLOWED = "disallowed"
    HELD = "held"
    REJECTED = "rejected"
    WARNING = "warning"
    INFO = "info"


# ------------------------------------------------------------------------ reference


class Employee(Base, TimestampMixin):
    __tablename__ = "employee"

    id: Mapped[int] = mapped_column(primary_key=True)
    emp_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    designation: Mapped[str] = mapped_column(String(120))
    department: Mapped[str] = mapped_column(String(80))
    cost_centre: Mapped[str] = mapped_column(String(16))
    city: Mapped[str] = mapped_column(String(80))
    role: Mapped[Role] = mapped_column(_enum(Role, 32))

    # FK to emp_code rather than id: the source CSV and the approval matrix both speak in codes,
    # and resolving a chain should not require a second lookup per level. Nullable because the
    # MD reports to nobody, which is also how the chain walk knows to stop.
    reporting_manager_code: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("employee.emp_code"), nullable=True, index=True
    )

    manager: Mapped[Employee | None] = relationship(
        remote_side=[emp_code], foreign_keys=[reporting_manager_code]
    )


class PolicyVersion(Base, ExternalIdMixin, TimestampMixin):
    """An effective-dated snapshot of the policy's parameters.

    A claim is evaluated against the version in force for its *travel dates*, and records which
    version it used. The document is already at Rev 4; there will be a Rev 5, and a claim
    settled under Rev 4 must still reproduce its own numbers afterwards.
    """

    __tablename__ = "policy_version"
    __table_args__ = (
        UniqueConstraint("document_id", "revision", name="uq_policy_document_revision"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(40))
    revision: Mapped[str] = mapped_column(String(16))
    effective_from: Mapped[date] = mapped_column(Date)
    # Open-ended until a successor closes it.
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


# ----------------------------------------------------------------------- trip


class TravelRequest(Base, ExternalIdMixin, TimestampMixin):
    __tablename__ = "travel_request"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The join key for everything downstream (policy §1.1). Human-facing: TRQ-2026-0001.
    trq_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employee.id"), index=True)

    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date] = mapped_column(Date)
    destination_city: Mapped[str] = mapped_column(String(80))
    city_class: Mapped[CityClass] = mapped_column(_enum(CityClass, 16))
    visiting_company: Mapped[str | None] = mapped_column(String(160), nullable=True)
    purpose: Mapped[str] = mapped_column(String(300))
    travel_category: Mapped[str] = mapped_column(String(60))
    mode_of_travel: Mapped[str] = mapped_column(String(40))
    cost_centre: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    advance_requested: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    issued_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    employee: Mapped[Employee] = relationship()
    estimate_lines: Mapped[list[TravelRequestEstimateLine]] = relationship(
        back_populates="travel_request", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("to_date >= from_date", name="ck_travel_request_dates_ordered"),
    )


class TravelRequestEstimateLine(Base):
    __tablename__ = "travel_request_estimate_line"

    id: Mapped[int] = mapped_column(primary_key=True)
    travel_request_id: Mapped[int] = mapped_column(
        ForeignKey("travel_request.id", ondelete="CASCADE"), index=True
    )
    head: Mapped[str] = mapped_column(String(60))
    basis: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    # The *plan*. Not evidence of who actually paid - see PaidBy.
    borne_by: Mapped[BorneBy] = mapped_column(_enum(BorneBy, 16))

    travel_request: Mapped[TravelRequest] = relationship(back_populates="estimate_lines")


class Advance(Base, ExternalIdMixin, TimestampMixin):
    __tablename__ = "advance"

    id: Mapped[int] = mapped_column(primary_key=True)
    travel_request_id: Mapped[int] = mapped_column(ForeignKey("travel_request.id"), index=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    disbursed_on: Mapped[date] = mapped_column(Date)


# -------------------------------------------------------------------- evidence


class EvidenceDocument(Base, ExternalIdMixin, TimestampMixin):
    __tablename__ = "evidence_document"

    id: Mapped[int] = mapped_column(primary_key=True)
    travel_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("travel_request.id"), nullable=True, index=True
    )

    source_filename: Mapped[str] = mapped_column(String(200))
    # Where the message actually lives. Null for anything seeded out of the pack, which is
    # always resolved against the pack's own mail directory. An employee upload is not in the
    # pack - it is under settings.upload_dir - so it has to carry its own location or the
    # pipeline would look for it in a read-only directory it will never be in.
    source_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    sender: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(400), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Resolved from the pack's placeholder attachment form, not from a decoded MIME part.
    attachment_path: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # Raw OCR text, kept so a reconciliation failure can be shown beside the source image.
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    doc_kind: Mapped[DocKind] = mapped_column(_enum(DocKind, 40), default=DocKind.UNKNOWN)
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        _enum(ExtractionStatus, 24), default=ExtractionStatus.PENDING
    )
    extractor_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Why this document needs a human: OCR did not reconcile, a required field is missing.
    needs_input_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Names a specific document, never "attached mail" (template legend line 65).
    proof_ref: Mapped[str] = mapped_column(String(120), index=True)

    line_items: Mapped[list[ExtractedLineItem]] = relationship(
        back_populates="evidence_document", cascade="all, delete-orphan"
    )


class ExtractedLineItem(Base, ExternalIdMixin, TimestampMixin):
    """One row per line on a bill.

    A consolidated bill is decomposed here: the sample hotel folio yields six of these, not one.
    Every interesting clause in the policy applies to a line, so a folio captured as a single
    total cannot be evaluated correctly.
    """

    __tablename__ = "extracted_line_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_document_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_document.id", ondelete="CASCADE"), index=True
    )

    merchant: Mapped[str | None] = mapped_column(String(200), nullable=True)
    txn_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    txn_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    gross_amount: Mapped[Decimal] = mapped_column(Money)
    # Apportioned share of a bill-level tax, or a stated per-line tax where the bill gives one.
    tax_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")

    # Lodging only. The §3.1 tariff limit is per night, so the check needs a divisor, and a
    # folio whose figures were typed in by hand has to carry it as well as one that was read.
    nights: Mapped[int | None] = mapped_column(Integer, nullable=True)

    category_hint: Mapped[str | None] = mapped_column(String(60), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Whose expense this is, per the evidence. A mismatch against the claimant is a rejection.
    payer_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bill_no: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # normalised merchant + timestamp + amount + bill number (policy §5.3).
    fingerprint: Mapped[str] = mapped_column(String(120), index=True)
    # Suppressed rather than deleted: a silently discarded duplicate is indistinguishable from
    # a receipt that was never ingested.
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("extracted_line_item.id"), nullable=True
    )

    # Not money, so a float is fine here.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_span: Mapped[str | None] = mapped_column(Text, nullable=True)

    evidence_document: Mapped[EvidenceDocument] = relationship(back_populates="line_items")


# ----------------------------------------------------------------------- claim


class SettlementClaim(Base, ExternalIdMixin, TimestampMixin):
    __tablename__ = "settlement_claim"

    id: Mapped[int] = mapped_column(primary_key=True)
    # One claim per trip. A resubmission reuses the same row and the same Travel Request ID
    # (policy §2.3), which is why this is unique rather than a history of claims.
    travel_request_id: Mapped[int] = mapped_column(
        ForeignKey("travel_request.id"), unique=True, index=True
    )
    policy_version_id: Mapped[int] = mapped_column(ForeignKey("policy_version.id"))

    status: Mapped[ClaimStatus] = mapped_column(
        _enum(ClaimStatus, 32), default=ClaimStatus.DRAFT, index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_count: Mapped[int] = mapped_column(Integer, default=0)

    # Optimistic lock. SQLite serialises writers, so this - not row-level locking - is what
    # actually prevents two approvers from both acting on one claim. It is the thing under test
    # in the concurrency case; see docs/agents/testing.md.
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Snapshot of the summary at evaluation time (template rows 44-50).
    employee_paid_gross: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    company_paid_memo: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    disallowed_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    net_reimbursable: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    advance_drawn: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    payable: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    recoverable: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))

    travel_request: Mapped[TravelRequest] = relationship()
    policy_version: Mapped[PolicyVersion] = relationship()
    lines: Mapped[list[ClaimLine]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    approval_steps: Mapped[list[ApprovalStep]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Template legend line 67: payable and recoverable are mutually exclusive.
        CheckConstraint("payable = 0 OR recoverable = 0", name="ck_claim_payable_xor_recoverable"),
    )


class ClaimLine(Base, ExternalIdMixin, TimestampMixin):
    __tablename__ = "claim_line"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(
        ForeignKey("settlement_claim.id", ondelete="CASCADE"), index=True
    )
    extracted_line_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("extracted_line_item.id"), nullable=True
    )

    head: Mapped[ExpenseHead] = mapped_column(_enum(ExpenseHead, 40))
    line_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str] = mapped_column(String(300))
    paid_by: Mapped[PaidBy] = mapped_column(_enum(PaidBy, 16))

    gross_amount: Mapped[Decimal] = mapped_column(Money)
    allowed_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    disallowed_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))

    status: Mapped[ClaimLineStatus] = mapped_column(_enum(ClaimLineStatus, 24))
    proof_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Populated when a line is withdrawn or rejected. Never a reason to delete the row.
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    claim: Mapped[SettlementClaim] = relationship(back_populates="lines")
    decisions: Mapped[list[PolicyDecision]] = relationship(
        back_populates="claim_line", cascade="all, delete-orphan"
    )


class PolicyDecision(Base):
    """Why a line came out the way it did, with the clause that decided it."""

    __tablename__ = "policy_decision"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_line_id: Mapped[int] = mapped_column(
        ForeignKey("claim_line.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(60), index=True)
    outcome: Mapped[DecisionOutcome] = mapped_column(_enum(DecisionOutcome, 20))
    # Signed effect on the line's allowed amount. Zero for warnings and info.
    amount_effect: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    reason: Mapped[str] = mapped_column(Text)
    # e.g. "§3.1" - shown to the employee and to approvers.
    policy_citation: Mapped[str] = mapped_column(String(40))

    claim_line: Mapped[ClaimLine] = relationship(back_populates="decisions")


# ------------------------------------------------------------------- workflow


class ApprovalStep(Base, ExternalIdMixin, TimestampMixin):
    """One level of the chain, resolved and persisted at submit time.

    Persisted rather than computed on read so the chain that actually applied to a submission
    is auditable after the matrix, the reporting line, or the claim value changes.
    """

    __tablename__ = "approval_step"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(
        ForeignKey("settlement_claim.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[Role] = mapped_column(_enum(Role, 32))
    approver_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employee.id"), nullable=True
    )

    decision: Mapped[ApprovalDecision] = mapped_column(
        _enum(ApprovalDecision, 16), default=ApprovalDecision.PENDING
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # A resubmission supersedes the previous chain rather than deleting it, so the history of
    # who approved what value survives.
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    submission_round: Mapped[int] = mapped_column(Integer, default=1)

    claim: Mapped[SettlementClaim] = relationship(back_populates="approval_steps")
    approver: Mapped[Employee | None] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "claim_id", "submission_round", "sequence", name="uq_approval_step_round_sequence"
        ),
    )


class PaymentRecord(Base, ExternalIdMixin, TimestampMixin):
    __tablename__ = "payment_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("settlement_claim.id"), index=True)
    # Policy §5.4: verified claims go out on the 10th and the 25th.
    run_date: Mapped[date] = mapped_column(Date)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    reference: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Notification(Base, ExternalIdMixin):
    """One addressed message to one person.

    Separate from ClaimEvent on purpose. ClaimEvent is an append-only audit of what the system
    did; a notification is addressed, has a read state, and is written for a human. Deriving an
    inbox from the audit log instead would mean every read toggle became a write to a table
    whose whole point is that it is never updated.
    """

    __tablename__ = "notification"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_employee_id: Mapped[int] = mapped_column(ForeignKey("employee.id"), index=True)
    travel_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("travel_request.id"), nullable=True, index=True
    )
    claim_id: Mapped[int | None] = mapped_column(
        ForeignKey("settlement_claim.id"), nullable=True, index=True
    )
    actor_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employee.id"), nullable=True)

    kind: Mapped[NotificationKind] = mapped_column(_enum(NotificationKind, 32))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    # Where the notification takes you. A human-facing TRQ id, not a row id.
    trq_id: Mapped[str | None] = mapped_column(String(20), nullable=True)

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    recipient: Mapped[Employee] = relationship(foreign_keys=[recipient_employee_id])
    actor: Mapped[Employee | None] = relationship(foreign_keys=[actor_employee_id])


Index(
    "ix_notification_recipient_created",
    Notification.recipient_employee_id,
    Notification.created_at,
)


class ClaimEvent(Base):
    """Append-only audit trail.

    Captures every ingestion, suppressed duplicate, rejected item, extracted value and
    subsequent edit, policy decision and approval action. UPDATE and DELETE are blocked by
    triggers in the baseline migration, so "append-only" is enforced rather than asserted.
    """

    __tablename__ = "claim_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    travel_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("travel_request.id"), nullable=True, index=True
    )
    claim_id: Mapped[int | None] = mapped_column(
        ForeignKey("settlement_claim.id"), nullable=True, index=True
    )
    actor_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employee.id"), nullable=True)

    action: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


Index("ix_claim_event_trq_at", ClaimEvent.travel_request_id, ClaimEvent.at)
