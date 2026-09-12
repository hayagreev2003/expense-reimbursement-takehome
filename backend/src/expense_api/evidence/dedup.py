"""Collapse the same transaction arriving more than once.

Policy §5.3: "Finance reconciles by bill number, date, amount and merchant." That is the
fingerprint, and the pack exercises it directly - the 17 Jun cab appears in three messages: a
payment-failure notice, the successful receipt, and a forward of that receipt the next morning.
The failure notice is already gone at classification; the other two have to collapse to one
172.00 line.

A suppressed duplicate is recorded and shown, never discarded. A receipt that was silently
dropped looks exactly like one that was never ingested, and the employee has no way to tell
which happened.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from expense_api.evidence.extractors.base import ExtractedItem

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class MatchStrength(enum.StrEnum):
    EXACT = "exact"
    # Same merchant, amount and date but a different time. Two genuine rides can look like
    # this, so it warns rather than merges - the employee decides.
    NEAR = "near"


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    index: int
    duplicate_of: int
    strength: MatchStrength
    reason: str


@dataclass
class DedupResult:
    kept: list[int] = field(default_factory=list)
    suppressed: list[DuplicateMatch] = field(default_factory=list)
    warnings: list[DuplicateMatch] = field(default_factory=list)


def normalise_merchant(value: str | None) -> str:
    if not value:
        return ""
    return _NON_ALNUM.sub("", value.lower())


def fingerprint(item: ExtractedItem) -> str:
    """The §5.3 reconciliation key: merchant, timestamp, amount, bill number.

    The timestamp rather than the date alone, because two cabs on one day are ordinary and
    would otherwise collapse into one.
    """
    when = (
        item.txn_datetime.isoformat()
        if item.txn_datetime
        else (item.txn_date.isoformat() if item.txn_date else "")
    )
    return "|".join(
        [
            normalise_merchant(item.merchant),
            when,
            f"{item.gross_amount:.2f}",
            (item.bill_no or "").strip().lower(),
        ]
    )


def _near_key(item: ExtractedItem) -> tuple[str, str, Decimal]:
    day = item.txn_date or (item.txn_datetime.date() if item.txn_datetime else None)
    return (
        normalise_merchant(item.merchant),
        day.isoformat() if day else "",
        item.gross_amount,
    )


def find_duplicates(items: Sequence[ExtractedItem]) -> DedupResult:
    """First occurrence wins; later identical ones are suppressed with a reason."""
    result = DedupResult()
    seen_exact: dict[str, int] = {}
    seen_near: dict[tuple[str, str, Decimal], int] = {}

    for index, item in enumerate(items):
        key = fingerprint(item)
        near = _near_key(item)

        if key in seen_exact:
            original = seen_exact[key]
            result.suppressed.append(
                DuplicateMatch(
                    index=index,
                    duplicate_of=original,
                    strength=MatchStrength.EXACT,
                    reason=(
                        f"Same merchant, time, amount and bill number as an item already "
                        f"claimed ({item.merchant or 'unknown merchant'}, "
                        f"{item.gross_amount}). Claimed once."
                    ),
                )
            )
            continue

        if near in seen_near:
            # Not merged. Two real trips can share a merchant, a day and a fare.
            result.warnings.append(
                DuplicateMatch(
                    index=index,
                    duplicate_of=seen_near[near],
                    strength=MatchStrength.NEAR,
                    reason=(
                        "Same merchant, date and amount as another item but a different "
                        "time. Kept both - confirm this is not the same trip twice."
                    ),
                )
            )

        seen_exact[key] = index
        seen_near.setdefault(near, index)
        result.kept.append(index)

    return result


def filter_out(items: Sequence[ExtractedItem], result: DedupResult) -> list[ExtractedItem]:
    """The items that survive dedup, in their original order."""
    return [items[index] for index in result.kept]
