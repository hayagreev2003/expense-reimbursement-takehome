"""The acceptance test: the whole pipeline over the real pack, end to end.

This is the requirements document in executable form, and the only test that proves the units
compose. Each assertion is named for the specific way the claim can go wrong, not for the
function it happens to exercise.

Every figure here was worked out by hand from `pack/` before any of the code existed.
"""

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.claims.pipeline import ClaimDraft, build_claim
from expense_api.config.settings import settings
from expense_api.db.models import ClaimLineStatus, ExpenseHead, PaidBy, Role
from expense_api.evidence.extractors.ocr import ocr_available
from expense_api.seed.employees import seed_employees
from expense_api.seed.policy import seed_policy_versions
from expense_api.seed.trip import seed_anchor_trip

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

EMAILS_DIR = settings.pack_dir / "sample_emails"
RECEIPTS_DIR = settings.pack_dir / "receipts"

pytest.importorskip("pytesseract")
if not ocr_available():  # pragma: no cover - depends on the host
    pytest.skip("tesseract is required for the dinner bill", allow_module_level=True)


@pytest_asyncio.fixture
async def claim(db_session: AsyncSession) -> ClaimDraft:
    """The sample trip, from the pack's own files, all the way to a settled claim."""
    await seed_employees(db_session, settings.pack_dir / "employee_master.csv")
    await seed_policy_versions(db_session)
    request = await seed_anchor_trip(db_session)

    return await build_claim(
        db_session,
        travel_request=request,
        emails_dir=EMAILS_DIR,
        receipts_dir=RECEIPTS_DIR,
    )


def _by_description(claim: ClaimDraft, needle: str):  # type: ignore[no-untyped-def]
    return next(o for o in claim.outcomes if needle.lower() in o.line.description.lower())


# ============================================================ the settlement


async def test_the_claim_settles_at_the_expected_figures(claim: ClaimDraft) -> None:
    summary = claim.summary

    assert summary.employee_paid_gross == Decimal("27318.04")
    assert summary.disallowed_total == Decimal("929.60")
    assert summary.net_reimbursable == Decimal("26388.44")
    assert summary.company_paid_memo == Decimal("10556.00")
    assert summary.advance_drawn == Decimal("20000.00")
    assert summary.payable == Decimal("6388.44")
    assert summary.recoverable == Decimal("0.00")


# ================================================================ the traps


async def test_trap_01_the_duplicate_cab_is_claimed_once(claim: ClaimDraft) -> None:
    """Messages 08, 09 and 10 are all the same 17 Jun ride.

    08 is a payment-failure notice and never reaches extraction; 09 and 10 both do, and collapse.
    """
    at_172 = [o for o in claim.outcomes if o.line.gross_amount == Decimal("172.00")]

    assert len(at_172) == 1
    assert len(claim.dedup.suppressed) == 1
    assert "172.00" in claim.dedup.suppressed[0].reason


async def test_trap_02_the_colleagues_expense_is_rejected_by_name(claim: ClaimDraft) -> None:
    """Deepa's 640.00 Chennai cab from May, forwarded with a note asking for it to be added."""
    line = _by_description(claim, "Guindy")

    assert line.status is ClaimLineStatus.REJECTED
    assert line.line.gross_amount == Decimal("640.00")
    reason = " ".join(d.reason for d in line.decisions)
    assert "Deepa" in reason
    # Rejected, not absorbed: it contributes nothing to the money.
    assert line.allowed_amount == Decimal("0.00")
    assert line.disallowed_amount == Decimal("0.00")


async def test_trap_03_promotional_mail_produces_no_claim_line(claim: ClaimDraft) -> None:
    assert "14_promo_noise.eml" in claim.set_aside
    assert not any("MONSOON" in o.line.description.upper() for o in claim.outcomes)


async def test_trap_04_the_payment_failure_notice_is_not_a_receipt(claim: ClaimDraft) -> None:
    """It carries a merchant, a date and an amount, and the real charge arrived separately."""
    assert "08_uber_payment_failed.eml" in claim.set_aside
    assert "not a receipt" in claim.set_aside["08_uber_payment_failed.eml"]


async def test_trap_05_company_paid_flights_are_memo_only(claim: ClaimDraft) -> None:
    """§3.2: employees do not claim centrally booked air travel."""
    flights = [o for o in claim.outcomes if o.line.paid_by is PaidBy.COMPANY]

    assert len(flights) == 2
    assert sum(o.line.gross_amount for o in flights) == Decimal("10556.00")
    assert all(o.status is ClaimLineStatus.MEMO for o in flights)
    assert all(o.allowed_amount == Decimal("0.00") for o in flights)
    assert claim.summary.company_paid_memo == Decimal("10556.00")


async def test_trap_06_folio_personal_items_are_disallowed_with_remarks(claim: ClaimDraft) -> None:
    """Template legend line 66: shown as disallowed, never silently omitted."""
    laundry = _by_description(claim, "Laundry")
    minibar = _by_description(claim, "Mini bar")

    assert laundry.status is ClaimLineStatus.DISALLOWED
    assert minibar.status is ClaimLineStatus.DISALLOWED
    for line in (laundry, minibar):
        remark = " ".join(d.reason for d in line.decisions)
        assert "§4" in remark
        assert line.disallowed_amount > Decimal("0.00")


async def test_trap_07_tax_on_disallowed_items_is_disallowed_with_them(claim: ClaimDraft) -> None:
    """The folio's 12% sits on the whole subtotal, including what policy will not pay."""
    laundry = _by_description(claim, "Laundry")
    minibar = _by_description(claim, "Mini bar")

    assert laundry.line.tax_share == Decimal("54.00")
    assert minibar.line.tax_share == Decimal("45.60")
    assert laundry.disallowed_amount == Decimal("504.00")
    assert minibar.disallowed_amount == Decimal("425.60")
    # 830.00 of charges plus 99.60 of tax.
    assert claim.summary.disallowed_total == Decimal("929.60")


async def test_trap_08_in_room_dining_is_a_meal_and_is_allowed(claim: ClaimDraft) -> None:
    """§4 does not list food. 1,120.00 plus 134.40 tax, inside a 1,500 Tier 1 daily cap."""
    dining = _by_description(claim, "In-room dining")

    assert dining.line.head is ExpenseHead.MEALS
    assert dining.status is ClaimLineStatus.ALLOWED
    assert dining.allowed_amount == Decimal("1254.40")


async def test_trap_09_a_compliant_tariff_produces_no_disallowance(claim: ClaimDraft) -> None:
    """5,750 per night against a Tier 1 limit of 6,000.

    The approving manager's email warns about past overspend. That is context about other
    claims, and disallowing on the strength of it would be wrong.
    """
    room = _by_description(claim, "Room charges")

    assert room.line.nights == 3
    assert room.line.gross_amount / room.line.nights == Decimal("5750")
    assert room.disallowed_amount == Decimal("0.00")
    assert room.allowed_amount == Decimal("19320.00")


async def test_trap_10_the_hosted_dinner_is_held_not_paid(claim: ClaimDraft) -> None:
    """§3.5: business entertainment, needing attendee names and prior HoD approval above 2,000."""
    dinner = _by_description(claim, "Dinner")

    assert dinner.line.head is ExpenseHead.BUSINESS_ENTERTAINMENT
    assert dinner.status is ClaimLineStatus.HELD
    assert dinner.line.gross_amount == Decimal("2255.00")
    reasons = " ".join(dinner.blocking_reasons)
    assert "names and organisation" in reasons
    assert "2000" in reasons


async def test_trap_11_the_unaccounted_night_is_flagged_not_filled(claim: ClaimDraft) -> None:
    """The folio covers 16-19 Jun; the return flight is the evening of the 20th."""
    assert claim.coverage_gaps == [date(2026, 6, 19)]
    # Flagged only. No line was invented for it.
    assert not any(o.line.line_date == date(2026, 6, 19) for o in claim.outcomes)


async def test_trap_12_routing_keys_on_the_value_after_disallowances(claim: ClaimDraft) -> None:
    """26,388.44 needs a Head of Department; 24,133.44 does not."""
    assert [step.role for step in claim.chain] == [
        Role.REPORTING_MANAGER,
        Role.HEAD_OF_DEPARTMENT,
        Role.FINANCE,
    ]
    assert claim.chain[0].approver is not None
    assert claim.chain[0].approver.emp_code == "NX-2210"
    assert claim.chain[1].approver is not None
    assert claim.chain[1].approver.emp_code == "NX-1108"


async def test_trap_12b_withdrawing_the_held_line_sheds_an_approval_level(
    db_session: AsyncSession,
) -> None:
    """The same claim, one line withdrawn, re-evaluated from scratch."""
    await seed_employees(db_session, settings.pack_dir / "employee_master.csv")
    await seed_policy_versions(db_session)
    request = await seed_anchor_trip(db_session)

    reduced = await build_claim(
        db_session,
        travel_request=request,
        emails_dir=EMAILS_DIR,
        receipts_dir=RECEIPTS_DIR,
        withdrawn_descriptions=frozenset({"Dinner, 4 covers"}),
    )

    assert reduced.summary.net_reimbursable == Decimal("24133.44")
    assert reduced.summary.payable == Decimal("4133.44")
    assert [step.role for step in reduced.chain] == [Role.REPORTING_MANAGER, Role.FINANCE]
    # Withdrawn, not deleted: still visible, with its reason.
    withdrawn = _by_description(reduced, "Dinner")
    assert withdrawn.status is ClaimLineStatus.WITHDRAWN


async def test_trap_13_the_folio_reconciles_against_its_own_subtotal(claim: ClaimDraft) -> None:
    """Amounts come from the message body, so the fold in the image costs nothing here.

    The guard is what makes that safe rather than lucky: had extraction fallen back to OCR, the
    five legible lines would sum to 13,450 against a stated 19,200 and the document would be
    held for a human instead of quietly understating the claim by 3,750. See
    test_extractors.py::test_extracting_the_folio_from_the_image_alone_is_caught_by_the_guard.
    """
    folio_lines = [
        o
        for o in claim.outcomes
        if "Keys" in (o.line.proof_ref or "")
        or o.line.description in {"Room charges", "Laundry", "Mini bar", "In-room dining"}
    ]

    assert sum(o.line.gross_amount for o in folio_lines) == Decimal("19200.00")
    assert sum(o.line.claimable for o in folio_lines) == Decimal("21504.00")
    assert "12_hotel_invoice.eml" not in claim.needs_input


# ==================================================== submission and evidence


async def test_the_claim_cannot_be_submitted_while_the_dinner_is_held(claim: ClaimDraft) -> None:
    assert not claim.can_submit
    assert any("Dinner" in reason for reason in claim.blocking_reasons)


async def test_nothing_that_was_seen_is_silently_missing(claim: ClaimDraft) -> None:
    """Every one of the fifteen messages is accounted for: claimed, rejected, or set aside."""
    accounted = len(claim.set_aside) + len(claim.needs_input)
    claimed_documents = {o.line.proof_ref for o in claim.outcomes if o.line.proof_ref}

    assert accounted + len(claimed_documents) >= 11
    assert claim.needs_input == {}


async def test_every_adverse_outcome_carries_a_policy_citation(claim: ClaimDraft) -> None:
    """An employee who cannot see why a figure changed will ask Finance - the follow-up this
    system exists to remove."""
    for outcome in claim.outcomes:
        for decision in outcome.decisions:
            if decision.outcome.value in {"disallowed", "held", "rejected"}:
                assert decision.citation, decision.reason
                assert decision.rule_id


async def test_every_reimbursable_line_names_its_source_document(claim: ClaimDraft) -> None:
    """Template legend line 65, and the property that makes any figure traceable."""
    for outcome in claim.outcomes:
        if outcome.line.paid_by is PaidBy.EMPLOYEE and outcome.status is ClaimLineStatus.ALLOWED:
            assert outcome.line.proof_ref
            assert "attached mail" not in outcome.line.proof_ref.lower()
