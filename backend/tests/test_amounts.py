"""Unit 4: parsing Indian-format money, including money OCR has damaged."""

from decimal import Decimal

import pytest

from expense_api.evidence.amounts import parse_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Ordinary forms from the pack.
        ("1,415.02", "1415.02"),
        ("743.00", "743.00"),
        ("172.00", "172.00"),
        ("2,255.00", "2255.00"),
        ("19,200.00", "19200.00"),
        ("21,504.00", "21504.00"),
        ("5,750.00", "5750.00"),
        ("INR 1,229.02", "1229.02"),
        ("Total  INR 1,415.02", "1415.02"),
        ("0.00", "0.00"),
        ("5750", "5750.00"),
        # Indian lakh grouping.
        ("1,00,000.00", "100000.00"),
        ("2,00,000", "200000.00"),
    ],
)
def test_parses_ordinary_amounts(raw: str, expected: str) -> None:
    assert parse_amount(raw) == Decimal(expected)


def test_recovers_the_amount_ocr_damaged_on_the_hotel_folio() -> None:
    """`5,750.00` comes back from tesseract as `5.750.00` where the fold crosses the line.

    Two separators, so all but the last are thousands separators. Reading it as 5.75 would
    understate that folio line by 5,744.25 and still look like a plausible number.
    """
    assert parse_amount("5.750.00") == Decimal("5750.00")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # A single separator followed by three digits is a thousands separator.
        ("5,750", "5750.00"),
        ("5.750", "5750.00"),
        # Followed by two digits it is the decimal point.
        ("5.75", "5.75"),
        ("5,75", "5.75"),
    ],
)
def test_disambiguates_a_single_separator_by_what_follows_it(raw: str, expected: str) -> None:
    assert parse_amount(raw) == Decimal(expected)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "Thank you, visit again",
        # Card digits, which OCR splits. These must never read as an amount - "****22 88"
        # becoming 2288 would invent a line item out of a payment method.
        "****2288",
        "****22 88",
        "CARD ****2288",
        "Table 12 Covers 4",
        None,
    ],
)
def test_returns_none_rather_than_guessing(raw: str | None) -> None:
    assert parse_amount(raw) is None


def test_never_returns_a_float() -> None:
    """A float here would defeat the Money column downstream."""
    value = parse_amount("27,318.04")

    assert isinstance(value, Decimal)
    assert value == Decimal("27318.04")


def test_quantises_to_paise() -> None:
    assert parse_amount("1,415.0") == Decimal("1415.00")
    assert parse_amount("100").as_tuple().exponent == -2  # type: ignore[union-attr]


def test_handles_a_negative_or_bracketed_amount() -> None:
    """Credit notes and refunds appear on folios."""
    assert parse_amount("-450.00") == Decimal("-450.00")
    assert parse_amount("(450.00)") == Decimal("-450.00")
