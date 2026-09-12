"""Unit 5: collapsing the same transaction arriving more than once (§5.3)."""

from datetime import date, datetime
from decimal import Decimal

from expense_api.evidence.dedup import (
    MatchStrength,
    filter_out,
    find_duplicates,
    fingerprint,
    normalise_merchant,
)
from expense_api.evidence.extractors.base import ExtractedItem


def _ride(
    amount: str = "172.00",
    when: datetime | None = None,
    merchant: str = "Uber",
    bill_no: str | None = None,
) -> ExtractedItem:
    moment = when or datetime(2026, 6, 17, 19, 35)
    return ExtractedItem(
        gross_amount=Decimal(amount),
        description="Vertex Technologies, Whitefield to Keys Prime Hotel, Whitefield",
        merchant=merchant,
        txn_date=moment.date(),
        txn_datetime=moment,
        bill_no=bill_no,
    )


def test_normalises_merchant_spelling() -> None:
    assert normalise_merchant("Uber") == normalise_merchant("UBER ")
    assert normalise_merchant("Keys Prime Whitefield") == "keysprimewhitefield"
    assert normalise_merchant(None) == ""


def test_the_resent_receipt_collapses_into_the_original() -> None:
    """Messages 09 and 10: the same 172.00 ride, sent twice. One claim line."""
    result = find_duplicates([_ride(), _ride()])

    assert result.kept == [0]
    assert len(result.suppressed) == 1
    assert result.suppressed[0].duplicate_of == 0
    assert result.suppressed[0].strength is MatchStrength.EXACT


def test_the_suppression_states_a_reason() -> None:
    """A duplicate silently dropped is indistinguishable from one never ingested."""
    result = find_duplicates([_ride(), _ride()])

    reason = result.suppressed[0].reason
    assert "172.00" in reason
    assert "Uber" in reason


def test_two_different_rides_on_one_day_are_both_kept() -> None:
    """Messages 06 and 07 are both 16 Jun. Collapsing them would lose a real fare."""
    result = find_duplicates(
        [
            _ride("1415.02", datetime(2026, 6, 16, 5, 20)),
            _ride("743.00", datetime(2026, 6, 16, 9, 52)),
        ]
    )

    assert result.kept == [0, 1]
    assert result.suppressed == []


def test_same_amount_different_time_warns_but_keeps_both() -> None:
    """Two genuine trips can share a merchant, a day and a fare. The employee decides."""
    result = find_duplicates(
        [
            _ride("172.00", datetime(2026, 6, 17, 19, 35)),
            _ride("172.00", datetime(2026, 6, 17, 21, 5)),
        ]
    )

    assert result.kept == [0, 1]
    assert result.suppressed == []
    assert len(result.warnings) == 1
    assert result.warnings[0].strength is MatchStrength.NEAR
    assert "confirm" in result.warnings[0].reason.lower()


def test_bill_number_separates_otherwise_identical_lines() -> None:
    """A hotel folio can legitimately show the same amount twice on the same day."""
    first = _ride("5750.00", datetime(2026, 6, 16), merchant="Keys Prime", bill_no="A-1")
    second = _ride("5750.00", datetime(2026, 6, 16), merchant="Keys Prime", bill_no="A-2")

    assert fingerprint(first) != fingerprint(second)
    assert find_duplicates([first, second]).suppressed == []


def test_fingerprint_uses_the_four_fields_policy_names() -> None:
    """§5.3: bill number, date, amount, merchant."""
    key = fingerprint(_ride("172.00", datetime(2026, 6, 17, 19, 35), bill_no="X9"))

    assert "uber" in key
    assert "172.00" in key
    assert "2026-06-17" in key
    assert "x9" in key


def test_an_item_with_no_timestamp_still_fingerprints() -> None:
    item = ExtractedItem(
        gross_amount=Decimal("450.00"), description="Laundry", merchant="Keys Prime"
    )

    assert fingerprint(item)
    assert find_duplicates([item, item]).kept == [0]


def test_date_only_items_compare_on_the_date() -> None:
    a = ExtractedItem(
        gross_amount=Decimal("450.00"),
        description="Laundry",
        merchant="Keys Prime",
        txn_date=date(2026, 6, 17),
    )

    assert find_duplicates([a, a]).suppressed[0].strength is MatchStrength.EXACT


def test_filter_out_returns_only_the_kept_items() -> None:
    items = [_ride(), _ride(), _ride("743.00", datetime(2026, 6, 16, 9, 52))]

    result = find_duplicates(items)
    kept = filter_out(items, result)

    assert len(kept) == 2
    assert [i.gross_amount for i in kept] == [Decimal("172.00"), Decimal("743.00")]


def test_nothing_is_suppressed_in_an_empty_or_single_list() -> None:
    assert find_duplicates([]).kept == []
    assert find_duplicates([_ride()]).kept == [0]
