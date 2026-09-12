"""Unit 7: who has to approve, given the claim's value and the reporting line."""

from decimal import Decimal

import pytest
import yaml

from expense_api.approvals.routing import (
    EmployeeRef,
    RoutingError,
    ancestors,
    resolve_chain,
    roles_for_value,
)
from expense_api.db.models import Role
from expense_api.policy.seed_paths import POLICY_YAML

PARAMS = yaml.safe_load(POLICY_YAML.read_text())

# The pack's reporting line.
DIRECTORY = {
    "NX-4471": EmployeeRef("NX-4471", "Chaitanya Reddy", Role.EMPLOYEE, "NX-2210"),
    "NX-2210": EmployeeRef("NX-2210", "Suresh Iyer", Role.REPORTING_MANAGER, "NX-1108"),
    "NX-1108": EmployeeRef("NX-1108", "Meera Krishnan", Role.HEAD_OF_DEPARTMENT, "NX-1002"),
    "NX-1002": EmployeeRef("NX-1002", "Arvind Rao", Role.HEAD_OF_DIVISION, "NX-1000"),
    "NX-1000": EmployeeRef("NX-1000", "Nandita Shah", Role.MD, None),
    "NX-3305": EmployeeRef("NX-3305", "Ravi Menon", Role.FINANCE, "NX-3300"),
    "NX-3300": EmployeeRef("NX-3300", "Kavitha Balan", Role.FINANCE, "NX-1002"),
}
CLAIMANT = DIRECTORY["NX-4471"]


def _chain(value: str, claimant: EmployeeRef = CLAIMANT, **kwargs: object):  # type: ignore[no-untyped-def]
    return resolve_chain(
        claim_value=Decimal(value),
        claimant=claimant,
        directory=DIRECTORY,
        params=PARAMS,
        **kwargs,  # type: ignore[arg-type]
    )


def test_the_reporting_line_walks_to_the_top() -> None:
    line = ancestors(CLAIMANT, DIRECTORY)

    assert [p.emp_code for p in line] == ["NX-2210", "NX-1108", "NX-1002", "NX-1000"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.00", [Role.REPORTING_MANAGER]),
        ("25000.00", [Role.REPORTING_MANAGER]),
        ("25001.00", [Role.REPORTING_MANAGER, Role.HEAD_OF_DEPARTMENT]),
        ("75000.00", [Role.REPORTING_MANAGER, Role.HEAD_OF_DEPARTMENT]),
        (
            "75001.00",
            [Role.REPORTING_MANAGER, Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_DIVISION],
        ),
        (
            "200001.00",
            [
                Role.REPORTING_MANAGER,
                Role.HEAD_OF_DEPARTMENT,
                Role.HEAD_OF_DIVISION,
                Role.MD,
            ],
        ),
    ],
)
def test_the_matrix_bands_match_the_policy(value: str, expected: list[Role]) -> None:
    assert roles_for_value(Decimal(value), PARAMS) == expected


def test_the_sample_claim_routes_to_manager_and_head_of_department() -> None:
    """26,388.44 sits in the 25,001-75,000 band."""
    chain = _chain("26388.44")

    assert [(s.role, s.approver.emp_code if s.approver else None) for s in chain] == [
        (Role.REPORTING_MANAGER, "NX-2210"),
        (Role.HEAD_OF_DEPARTMENT, "NX-1108"),
        (Role.FINANCE, "NX-3300"),
    ]


def test_withdrawing_the_held_line_sheds_the_head_of_department() -> None:
    """The trap: routing is keyed on the value *after* disallowances.

    26,388.44 needs two business approvals. Withdraw the 2,255.00 entertainment line and the
    claim is 24,133.44 - below the 25,000 boundary, and the Head of Department is no longer
    required. Caching the chain across an edit would send it to an approver it does not need.
    """
    before = _chain("26388.44")
    after = _chain("24133.44")

    assert [s.role for s in before] == [
        Role.REPORTING_MANAGER,
        Role.HEAD_OF_DEPARTMENT,
        Role.FINANCE,
    ]
    assert [s.role for s in after] == [Role.REPORTING_MANAGER, Role.FINANCE]


def test_finance_verification_is_appended_at_every_value() -> None:
    """§2.1: required on every claim regardless of value."""
    for value in ("100.00", "26388.44", "500000.00"):
        assert _chain(value)[-1].role is Role.FINANCE


def test_a_large_claim_adds_the_division_head_and_the_md() -> None:
    chain = _chain("250000.00")

    assert [s.role for s in chain] == [
        Role.REPORTING_MANAGER,
        Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_DIVISION,
        Role.MD,
        Role.FINANCE,
    ]


def test_international_travel_requires_the_md_at_any_value() -> None:
    chain = _chain("5000.00", international=True)

    assert Role.MD in [s.role for s in chain]


def test_a_manager_claiming_skips_their_own_level() -> None:
    """§2.2. Suresh is the Reporting Manager; nobody above him holds that role, so the level
    is skipped and the Head of Department acts instead of it sitting pending forever."""
    chain = _chain("26388.44", claimant=DIRECTORY["NX-2210"])

    rm = next(s for s in chain if s.role is Role.REPORTING_MANAGER)
    assert rm.approver is None
    assert rm.note is not None
    assert "§2.2" in rm.note

    hod = next(s for s in chain if s.role is Role.HEAD_OF_DEPARTMENT)
    assert hod.approver is not None
    assert hod.approver.emp_code == "NX-1108"


def test_steps_are_sequenced_from_one() -> None:
    chain = _chain("26388.44")

    assert [s.sequence for s in chain] == [1, 2, 3]


def test_a_broken_reporting_line_fails_rather_than_routing_to_nobody() -> None:
    orphan = EmployeeRef("NX-9999", "Orphan", Role.EMPLOYEE, "NX-MISSING")

    with pytest.raises(RoutingError, match="not in the employee master"):
        ancestors(orphan, DIRECTORY)


def test_a_cyclic_reporting_line_is_caught() -> None:
    """A bad CSV import produces exactly this, and it would otherwise hang the request."""
    cyclic = {
        "A": EmployeeRef("A", "A", Role.EMPLOYEE, "B"),
        "B": EmployeeRef("B", "B", Role.REPORTING_MANAGER, "A"),
    }

    with pytest.raises(RoutingError, match="loops back"):
        ancestors(cyclic["A"], cyclic)


def test_an_uncovered_value_fails_loudly() -> None:
    with pytest.raises(RoutingError, match="No approval band"):
        roles_for_value(Decimal("-1.00"), PARAMS)
