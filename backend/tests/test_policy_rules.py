"""Unit 6: the rule engine, against the sample trip's known figures."""

from datetime import date
from decimal import Decimal

import yaml

from expense_api.claims.summary import summarise
from expense_api.db.models import ClaimLineStatus, ExpenseHead, PaidBy
from expense_api.policy.engine import evaluate_lines
from expense_api.policy.registry import EvaluationContext, LineUnderReview, Outcome
from expense_api.policy.seed_paths import POLICY_YAML
from expense_api.policy.tax import apportion_tax

PARAMS = yaml.safe_load(POLICY_YAML.read_text())


def _context(**overrides: object) -> EvaluationContext:
    defaults: dict = {
        "params": PARAMS,
        "city_class": "Tier 1",
        "trip_from": date(2026, 6, 16),
        "trip_to": date(2026, 6, 20),
        "claimant_name": "Chaitanya Reddy",
    }
    defaults.update(overrides)
    return EvaluationContext(**defaults)  # type: ignore[arg-type]


def _line(
    head: ExpenseHead,
    description: str,
    gross: str,
    *,
    tax: str = "0.00",
    nights: int | None = None,
    when: date | None = date(2026, 6, 17),
    proof: str | None = "12_hotel_invoice.eml#hotel_invoice_1188.png",
    paid_by: PaidBy = PaidBy.EMPLOYEE,
) -> LineUnderReview:
    return LineUnderReview(
        head=head,
        description=description,
        gross_amount=Decimal(gross),
        tax_share=Decimal(tax),
        paid_by=paid_by,
        line_date=when,
        nights=nights,
        proof_ref=proof,
    )


# ---------------------------------------------------------------- §4 exclusions


def test_laundry_is_disallowed_with_its_apportioned_tax() -> None:
    outcome = evaluate_lines(
        [_line(ExpenseHead.MISC, "Laundry", "450.00", tax="54.00")], _context()
    )[0]

    assert outcome.status is ClaimLineStatus.DISALLOWED
    assert outcome.disallowed_amount == Decimal("504.00")
    assert outcome.allowed_amount == Decimal("0.00")
    reason = outcome.decisions[0].reason
    assert "§4" in reason and "54.00" in reason


def test_mini_bar_is_disallowed_with_its_apportioned_tax() -> None:
    outcome = evaluate_lines(
        [_line(ExpenseHead.MISC, "Mini bar", "380.00", tax="45.60")], _context()
    )[0]

    assert outcome.disallowed_amount == Decimal("425.60")


def test_every_disallowance_cites_a_clause() -> None:
    outcome = evaluate_lines([_line(ExpenseHead.MISC, "Laundry", "450.00")], _context())[0]

    disallowals = [d for d in outcome.decisions if d.outcome is Outcome.DISALLOWED]
    assert disallowals
    assert all(d.citation for d in disallowals)
    assert all(d.rule_id for d in disallowals)


def test_a_bar_snack_is_not_caught_by_mini_bar() -> None:
    """Word-boundary matching. "Barista" and "bar snack" are not the mini bar."""
    outcome = evaluate_lines([_line(ExpenseHead.MEALS, "Bar snack", "200.00")], _context())[0]

    assert outcome.status is not ClaimLineStatus.DISALLOWED


# ------------------------------------------------------------------ §3.1 lodging


def test_the_sample_tariff_passes_the_tier_1_limit() -> None:
    """5,750 per night against a 6,000 limit. The near-miss the pack sets up.

    The approving manager's email warns about past overspend; that is context about other
    claims, not evidence about this one.
    """
    outcome = evaluate_lines(
        [_line(ExpenseHead.LODGING, "Room charges", "17250.00", tax="2070.00", nights=3)],
        _context(),
    )[0]

    assert outcome.status is ClaimLineStatus.ALLOWED
    assert outcome.disallowed_amount == Decimal("0.00")
    assert outcome.allowed_amount == Decimal("19320.00")


def test_the_limit_is_measured_before_tax() -> None:
    """§3.1 caps the room tariff excluding taxes, and taxes on it are reimbursable in full.

    Comparing the tax-inclusive figure would fail a compliant stay: 19,320/3 = 6,440 per night
    reads as a breach when the tariff is 5,750.
    """
    outcome = evaluate_lines(
        [_line(ExpenseHead.LODGING, "Room charges", "17250.00", tax="2070.00", nights=3)],
        _context(),
    )[0]

    assert outcome.disallowed_amount == Decimal("0.00")


def test_tariff_over_the_limit_disallows_only_the_excess() -> None:
    outcome = evaluate_lines(
        [_line(ExpenseHead.LODGING, "Room charges", "19500.00", nights=3)], _context()
    )[0]

    # 6,500 per night against a 6,000 limit, over three nights.
    assert outcome.disallowed_amount == Decimal("1500.00")
    assert outcome.allowed_amount == Decimal("18000.00")
    assert outcome.status is ClaimLineStatus.ALLOWED


def test_a_tier_3_stay_uses_the_tier_3_limit() -> None:
    outcome = evaluate_lines(
        [_line(ExpenseHead.LODGING, "Room charges", "4000.00", nights=1)],
        _context(city_class="Tier 3"),
    )[0]

    assert outcome.disallowed_amount == Decimal("1200.00")  # 4,000 against a 2,800 limit


def test_an_unclassified_city_warns_rather_than_guessing() -> None:
    outcome = evaluate_lines(
        [_line(ExpenseHead.LODGING, "Room charges", "5000.00", nights=1)],
        _context(city_class="Tier 9"),
    )[0]

    warnings = [d for d in outcome.decisions if d.outcome is Outcome.WARNING]
    assert warnings
    assert "confirm" in warnings[0].reason.lower()


# -------------------------------------------------------------------- §3.3 meals


def test_in_room_dining_is_allowed_within_the_daily_cap() -> None:
    """1,120.00 plus 134.40 of apportioned tax = 1,254.40, against a Tier 1 cap of 1,500."""
    outcome = evaluate_lines(
        [
            _line(
                ExpenseHead.MEALS,
                "In-room dining",
                "1120.00",
                tax="134.40",
                when=date(2026, 6, 18),
            )
        ],
        _context(),
    )[0]

    assert outcome.status is ClaimLineStatus.ALLOWED
    assert outcome.allowed_amount == Decimal("1254.40")


def test_two_meals_on_one_day_are_capped_together() -> None:
    """Neither line breaches 1,500 alone; together they claim 1,800."""
    outcomes = evaluate_lines(
        [
            _line(ExpenseHead.MEALS, "Lunch", "900.00", when=date(2026, 6, 18)),
            _line(ExpenseHead.MEALS, "Dinner", "900.00", when=date(2026, 6, 18)),
        ],
        _context(),
    )

    total_disallowed = sum(o.disallowed_amount for o in outcomes)
    assert total_disallowed == Decimal("300.00")


def test_meals_on_different_days_do_not_pool() -> None:
    outcomes = evaluate_lines(
        [
            _line(ExpenseHead.MEALS, "Dinner", "1400.00", when=date(2026, 6, 17)),
            _line(ExpenseHead.MEALS, "Dinner", "1400.00", when=date(2026, 6, 18)),
        ],
        _context(),
    )

    assert all(o.disallowed_amount == Decimal("0.00") for o in outcomes)


def test_a_meal_over_500_without_a_bill_is_held() -> None:
    outcome = evaluate_lines(
        [_line(ExpenseHead.MEALS, "Dinner", "900.00", proof=None)], _context()
    )[0]

    assert outcome.status is ClaimLineStatus.HELD
    assert any("bill" in r for r in outcome.blocking_reasons)


# ---------------------------------------------------------- §3.5 entertainment


def test_the_dinner_is_held_for_attendees_and_prior_approval() -> None:
    """2,255.00, four covers, no names on file and no prior HoD approval for the trip."""
    outcome = evaluate_lines(
        [
            _line(
                ExpenseHead.BUSINESS_ENTERTAINMENT,
                "Dinner, 4 covers",
                "2255.00",
                when=date(2026, 6, 18),
                proof="11_dinner_bill.eml#dinner_bill_18jun.png",
            )
        ],
        _context(),
    )[0]

    assert outcome.status is ClaimLineStatus.HELD
    reasons = " ".join(outcome.blocking_reasons)
    assert "names and organisation" in reasons
    assert "2000" in reasons
    # Held, not disallowed: the amount stands while the employee decides what to do.
    assert outcome.allowed_amount == Decimal("2255.00")


def test_entertainment_is_released_once_both_conditions_are_met() -> None:
    outcome = evaluate_lines(
        [
            _line(
                ExpenseHead.BUSINESS_ENTERTAINMENT,
                "Dinner, 4 covers",
                "2255.00",
                when=date(2026, 6, 18),
            )
        ],
        _context(
            entertainment_attendees=["R Kulkarni (Vertex Technologies)"],
            entertainment_prior_approval=True,
        ),
    )[0]

    assert outcome.status is ClaimLineStatus.ALLOWED


def test_small_entertainment_needs_names_but_not_prior_approval() -> None:
    outcome = evaluate_lines(
        [_line(ExpenseHead.BUSINESS_ENTERTAINMENT, "Coffee with client", "800.00")],
        _context(entertainment_attendees=["A Rao (Vertex)"]),
    )[0]

    assert outcome.status is ClaimLineStatus.ALLOWED


# ---------------------------------------------------------------- §3.4 and §5.2


def test_conveyance_is_allowed_on_actuals() -> None:
    outcome = evaluate_lines([_line(ExpenseHead.TRANSPORT, "Baner to PNQ", "1415.02")], _context())[
        0
    ]

    assert outcome.status is ClaimLineStatus.ALLOWED
    assert outcome.allowed_amount == Decimal("1415.02")


def test_a_line_without_proof_is_held() -> None:
    outcome = evaluate_lines(
        [_line(ExpenseHead.TRANSPORT, "Cab", "300.00", proof=None)], _context()
    )[0]

    assert outcome.status is ClaimLineStatus.HELD
    assert any("§5.2" in d.citation for d in outcome.decisions if d.outcome is Outcome.HELD)


def test_company_paid_memo_lines_need_no_proof() -> None:
    """Nothing is being reimbursed, so there is nothing for a proof reference to support."""
    outcomes = evaluate_lines(
        [_line(ExpenseHead.TRANSPORT, "6E-6284", "5016.00", proof=None, paid_by=PaidBy.COMPANY)],
        _context(),
        preset_statuses={0: ClaimLineStatus.MEMO},
    )

    assert outcomes[0].status is ClaimLineStatus.MEMO
    assert outcomes[0].allowed_amount == Decimal("0.00")


def test_a_rejected_line_is_not_a_disallowed_line() -> None:
    """Someone else's expense was never this claim's to disallow, so it adds nothing to row 46."""
    outcome = evaluate_lines(
        [_line(ExpenseHead.TRANSPORT, "Guindy to MAA", "640.00")],
        _context(),
        preset_statuses={0: ClaimLineStatus.REJECTED},
    )[0]

    assert outcome.status is ClaimLineStatus.REJECTED
    assert outcome.disallowed_amount == Decimal("0.00")
    assert outcome.allowed_amount == Decimal("0.00")


# ----------------------------------------------------- the whole sample claim


def _sample_claim() -> list[LineUnderReview]:
    """Every line of the anchor trip, with folio tax already apportioned."""
    folio = [Decimal("17250.00"), Decimal("450.00"), Decimal("380.00"), Decimal("1120.00")]
    shares = apportion_tax(folio, Decimal("2304.00"))

    return [
        _line(
            ExpenseHead.LODGING,
            "Room charges",
            "17250.00",
            tax=str(shares[0]),
            nights=3,
            when=date(2026, 6, 16),
        ),
        _line(ExpenseHead.MISC, "Laundry", "450.00", tax=str(shares[1]), when=date(2026, 6, 17)),
        _line(ExpenseHead.MISC, "Mini bar", "380.00", tax=str(shares[2]), when=date(2026, 6, 18)),
        _line(
            ExpenseHead.MEALS,
            "In-room dining",
            "1120.00",
            tax=str(shares[3]),
            when=date(2026, 6, 18),
        ),
        _line(ExpenseHead.TRANSPORT, "Baner to PNQ", "1415.02", when=date(2026, 6, 16)),
        _line(ExpenseHead.TRANSPORT, "BLR to hotel", "743.00", when=date(2026, 6, 16)),
        _line(ExpenseHead.TRANSPORT, "Vertex to hotel", "172.00", when=date(2026, 6, 17)),
        _line(ExpenseHead.TRANSPORT, "PNQ to Baner", "1229.02", when=date(2026, 6, 20)),
        _line(
            ExpenseHead.BUSINESS_ENTERTAINMENT,
            "Dinner, 4 covers",
            "2255.00",
            when=date(2026, 6, 18),
        ),
        _line(
            ExpenseHead.TRANSPORT,
            "6E-6284 PNQ-BLR",
            "5016.00",
            when=date(2026, 6, 16),
            paid_by=PaidBy.COMPANY,
        ),
        _line(
            ExpenseHead.TRANSPORT,
            "6E-6491 BLR-PNQ",
            "5540.00",
            when=date(2026, 6, 20),
            paid_by=PaidBy.COMPANY,
        ),
        _line(ExpenseHead.TRANSPORT, "Guindy to MAA", "640.00", when=date(2026, 5, 12)),
    ]


def test_the_sample_claim_settles_at_the_expected_figures() -> None:
    """Every number here comes from the pack, worked by hand before any of this was written."""
    lines = _sample_claim()
    outcomes = evaluate_lines(
        lines,
        _context(),
        preset_statuses={
            9: ClaimLineStatus.MEMO,
            10: ClaimLineStatus.MEMO,
            11: ClaimLineStatus.REJECTED,
        },
    )

    summary = summarise(outcomes, advance_drawn=Decimal("20000.00"))

    assert summary.employee_paid_gross == Decimal("27318.04")
    assert summary.disallowed_total == Decimal("929.60")
    assert summary.net_reimbursable == Decimal("26388.44")
    assert summary.company_paid_memo == Decimal("10556.00")
    assert summary.advance_drawn == Decimal("20000.00")
    assert summary.payable == Decimal("6388.44")
    assert summary.recoverable == Decimal("0.00")


def test_withdrawing_the_entertainment_line_drops_the_claim_below_the_band() -> None:
    """26,388.44 - 2,255.00 = 24,133.44, crossing the 25,000 approval threshold."""
    lines = _sample_claim()
    outcomes = evaluate_lines(
        lines,
        _context(),
        preset_statuses={
            8: ClaimLineStatus.WITHDRAWN,
            9: ClaimLineStatus.MEMO,
            10: ClaimLineStatus.MEMO,
            11: ClaimLineStatus.REJECTED,
        },
    )

    summary = summarise(outcomes, advance_drawn=Decimal("20000.00"))

    assert summary.net_reimbursable == Decimal("24133.44")
    assert summary.payable == Decimal("4133.44")


def test_a_claim_below_the_advance_is_recoverable_not_payable() -> None:
    outcomes = evaluate_lines([_line(ExpenseHead.TRANSPORT, "Cab", "500.00")], _context())
    summary = summarise(outcomes, advance_drawn=Decimal("20000.00"))

    assert summary.payable == Decimal("0.00")
    assert summary.recoverable == Decimal("19500.00")


def test_payable_and_recoverable_are_never_both_set() -> None:
    for advance in ("0.00", "100.00", "26388.44", "50000.00"):
        outcomes = evaluate_lines(
            _sample_claim(),
            _context(),
            preset_statuses={
                9: ClaimLineStatus.MEMO,
                10: ClaimLineStatus.MEMO,
                11: ClaimLineStatus.REJECTED,
            },
        )
        summary = summarise(outcomes, advance_drawn=Decimal(advance))
        assert summary.payable == Decimal("0.00") or summary.recoverable == Decimal("0.00")


def test_evaluating_against_a_stricter_policy_changes_the_outcome() -> None:
    """Proves the limits are read from the version, not baked into the code."""
    stricter = {
        **PARAMS,
        "lodging": {
            **PARAMS["lodging"],
            "limits_per_night": {**PARAMS["lodging"]["limits_per_night"], "Tier 1": 5000},
        },
    }

    outcome = evaluate_lines(
        [_line(ExpenseHead.LODGING, "Room charges", "17250.00", nights=3)],
        _context(params=stricter),
    )[0]

    assert outcome.disallowed_amount == Decimal("2250.00")  # (5750 - 5000) x 3
