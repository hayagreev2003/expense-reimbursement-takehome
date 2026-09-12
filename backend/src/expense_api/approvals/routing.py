"""Work out who has to approve a claim, from its value and the reporting line.

Two things make this less mechanical than it looks.

The band is keyed on the claim value **after disallowances**, so routing cannot be decided until
the policy engine has run, and it has to be recomputed on every resubmission. The sample claim
sits at 26,388.44, which is 1,388.44 above the 25,000 boundary - withdrawing one held line drops
it under and sheds a level.

And §2.2: an approver cannot approve their own claim, so where the claimant holds the role a
level needs, that level is skipped and the next one up acts. That falls out of walking upward
from the claimant rather than searching the whole org: the claimant is never their own ancestor.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from expense_api.db.models import Role


@dataclass(frozen=True, slots=True)
class EmployeeRef:
    """The little of an employee that routing needs."""

    emp_code: str
    name: str
    role: Role
    reporting_manager_code: str | None = None


@dataclass(frozen=True, slots=True)
class ChainStep:
    sequence: int
    role: Role
    approver: EmployeeRef | None
    # Why nobody fills this level, when nobody does.
    note: str | None = None


class RoutingError(Exception):
    """The chain cannot be resolved, and guessing would be worse than failing."""


def ancestors(
    claimant: EmployeeRef, directory: dict[str, EmployeeRef], *, max_depth: int = 12
) -> list[EmployeeRef]:
    """The reporting line above the claimant, nearest first.

    Depth-capped rather than trusted: a cycle in the employee master would otherwise hang the
    request, and a cycle is exactly the kind of thing a bad CSV import produces.
    """
    chain: list[EmployeeRef] = []
    seen = {claimant.emp_code}
    code = claimant.reporting_manager_code

    while code and len(chain) < max_depth:
        if code in seen:
            raise RoutingError(f"Reporting line for {claimant.emp_code} loops back to {code}")
        manager = directory.get(code)
        if manager is None:
            raise RoutingError(
                f"{claimant.emp_code} reports to {code}, who is not in the employee master"
            )
        chain.append(manager)
        seen.add(code)
        code = manager.reporting_manager_code

    return chain


def roles_for_value(claim_value: Decimal, params: dict[str, Any]) -> list[Role]:
    """The business approval roles the §2 matrix requires at this value."""
    matrix = params.get("approval_matrix") or []

    for band in matrix:
        minimum = Decimal(str(band.get("min", 0)))
        maximum = band.get("max")
        upper = Decimal(str(maximum)) if maximum is not None else None
        if claim_value >= minimum and (upper is None or claim_value <= upper):
            return [Role(role) for role in band["roles"]]

    raise RoutingError(f"No approval band covers a claim value of {claim_value}")


def resolve_chain(
    *,
    claim_value: Decimal,
    claimant: EmployeeRef,
    directory: dict[str, EmployeeRef],
    params: dict[str, Any],
    international: bool = False,
) -> list[ChainStep]:
    """The ordered approval chain for this claim, ending with Finance verification."""
    required = roles_for_value(claim_value, params)

    if international and params.get("approvals", {}).get("international_requires_md"):
        # Any international travel needs the full chain plus MD, whatever the value.
        for role in (
            Role.REPORTING_MANAGER,
            Role.HEAD_OF_DEPARTMENT,
            Role.HEAD_OF_DIVISION,
            Role.MD,
        ):
            if role not in required:
                required.append(role)

    line = ancestors(claimant, directory)
    steps: list[ChainStep] = []

    for role in required:
        approver = next((person for person in line if person.role is role), None)

        if approver is None:
            # §2.2. The claimant holds this role themselves, so nobody above them fills it and
            # the level is skipped rather than left pending forever.
            steps.append(
                ChainStep(
                    sequence=len(steps) + 1,
                    role=role,
                    approver=None,
                    note=(
                        f"Skipped: no {role.value} above {claimant.name} in the reporting line. "
                        f"An approver cannot approve their own claim (§2.2)."
                    ),
                )
            )
            continue

        steps.append(ChainStep(sequence=len(steps) + 1, role=role, approver=approver))

    # §2.1: Finance verification on every claim regardless of value.
    if params.get("approvals", {}).get("finance_verification_always", True):
        finance = _first_finance(directory)
        steps.append(ChainStep(sequence=len(steps) + 1, role=Role.FINANCE, approver=finance))

    return steps


def _first_finance(directory: dict[str, EmployeeRef]) -> EmployeeRef | None:
    """Lowest employee code among Finance staff, for a stable and predictable assignment."""
    finance = sorted(
        (person for person in directory.values() if person.role is Role.FINANCE),
        key=lambda person: person.emp_code,
    )
    return finance[0] if finance else None
