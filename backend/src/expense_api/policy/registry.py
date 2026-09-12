"""Rule registration.

Rules are functions keyed by a stable id, each carrying the clause it enforces. Registering
them rather than calling them in a fixed sequence means every outcome can name the rule and the
citation that produced it, and adding a clause is adding a function rather than editing a
chain of ifs.

Parameters live in the policy version's payload; only the logic lives here. A full declarative
DSL was considered and rejected - there is one policy document, and clauses like tax
apportionment do not reduce to parameters.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from expense_api.db.models import ExpenseHead, PaidBy

_ZERO = Decimal("0.00")


class Outcome(enum.StrEnum):
    ALLOWED = "allowed"
    DISALLOWED = "disallowed"
    HELD = "held"
    REJECTED = "rejected"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Decision:
    """Why a line came out the way it did, and which clause decided it."""

    rule_id: str
    outcome: Outcome
    reason: str
    citation: str
    # How much this decision removes from the line's reimbursable amount. Zero for warnings.
    amount_effect: Decimal = _ZERO


@dataclass(frozen=True, slots=True)
class LineUnderReview:
    """One claim line, as the rules see it."""

    head: ExpenseHead
    description: str
    gross_amount: Decimal
    paid_by: PaidBy
    line_date: date | None = None
    # This line's share of a bill-level tax, already apportioned. Rides with its line: if the
    # charge is disallowed, so is the tax on it.
    tax_share: Decimal = _ZERO
    nights: int | None = None
    proof_ref: str | None = None
    # Set by drafting for third-party expenses and company-paid memo rows.
    preset_reason: str | None = None

    @property
    def claimable(self) -> Decimal:
        return self.gross_amount + self.tax_share


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """Everything a rule needs beyond the line itself."""

    params: dict[str, Any]
    city_class: str
    trip_from: date
    trip_to: date
    claimant_name: str
    # §3.5 needs both to release a Business Entertainment line.
    entertainment_attendees: list[str] = field(default_factory=list)
    entertainment_prior_approval: bool = False
    # Meal caps are per day across every meal line, so a rule cannot judge one line alone.
    meals_claimed_by_date: dict[date, Decimal] = field(default_factory=dict)

    def limit(self, *path: str) -> Any:
        node: Any = self.params
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node


RuleFn = Callable[[LineUnderReview, EvaluationContext], list[Decision]]

_REGISTRY: dict[str, tuple[str, RuleFn]] = {}


def rule(rule_id: str, citation: str) -> Callable[[RuleFn], RuleFn]:
    """Register a rule under a stable id and the clause it enforces."""

    def register(fn: RuleFn) -> RuleFn:
        if rule_id in _REGISTRY:
            raise ValueError(f"Rule {rule_id!r} is already registered")
        _REGISTRY[rule_id] = (citation, fn)
        return fn

    return register


def registered_rules() -> Iterator[tuple[str, str, RuleFn]]:
    """(rule_id, citation, fn) for every rule, in registration order."""
    for rule_id, (citation, fn) in _REGISTRY.items():
        yield rule_id, citation, fn


def citation_for(rule_id: str) -> str:
    return _REGISTRY[rule_id][0]


def clear_registry_for_tests() -> None:  # pragma: no cover - test helper
    _REGISTRY.clear()
