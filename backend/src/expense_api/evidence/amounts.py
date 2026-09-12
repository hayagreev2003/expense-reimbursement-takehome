"""Parse Indian-format money out of text, including text OCR has damaged.

The separator rule is the whole job. Indian bills group as 1,00,000.00, tesseract turns commas
into full stops when a fold or a crease crosses a line, and both forms have to land on the same
Decimal. `5,750.00` reaching the pipeline as `5.75` would understate a folio line by 5,744.25
while still looking like a plausible amount.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_PAISE = Decimal("0.01")

# A run of digits and separators, optionally signed or bracketed. Deliberately narrow: it must
# not match "****22 88", which is a masked card number, not 2288.
_AMOUNT = re.compile(r"(?<![\d*])\(?-?\d[\d.,]*\)?(?![\d*])")

_SEPARATORS = re.compile(r"[.,]")

# A currency marker immediately before the number is enough to make a bare integer an amount.
# The word boundary is load-bearing: without it "Table 12 Covers 4" matches, because "Covers"
# ends in "rs", and a seat count becomes a four-rupee charge.
_CURRENCY = re.compile(r"(?:\bINR|\bRs\.?|₹)\s*$", re.I)


def parse_amount(raw: str | None) -> Decimal | None:
    """The last amount-looking token in `raw`, or None.

    Returns None rather than guessing. A wrong amount is worse than a missing one: a missing
    one fails reconciliation loudly, a wrong one quietly changes what the company pays.
    """
    if not raw:
        return None

    text = raw.strip()
    # Masked card numbers are the main false positive on these receipts.
    if "*" in text:
        return None

    matches = list(_AMOUNT.finditer(text))
    if not matches:
        return None

    # Bills put the number last ("Total  INR 1,415.02"), so prefer the rightmost token.
    for match in reversed(matches):
        if not _is_amount_shaped(text, match):
            continue
        value = _to_decimal(match.group())
        if value is not None:
            return value
    return None


def _is_amount_shaped(text: str, match: re.Match[str]) -> bool:
    """Reject a bare integer sitting inside prose.

    "Table 12 Covers 4" is a real line on the dinner bill, and reading its trailing 4 as a
    four-rupee charge would invent a line item out of a seat count. A number with no separator
    counts as money only when it stands alone or carries a currency marker.
    """
    token = match.group()
    if _SEPARATORS.search(token):
        return True
    if token.strip("()-") == text.strip("()-"):
        return True
    return bool(_CURRENCY.search(text[: match.start()]))


def _to_decimal(token: str) -> Decimal | None:
    negative = token.startswith("-") or (token.startswith("(") and token.endswith(")"))
    body = token.strip("()-")

    if not body or not body[0].isdigit():
        return None

    positions = [m.start() for m in _SEPARATORS.finditer(body)]

    if not positions:
        digits, fraction = body, ""
    else:
        last = positions[-1]
        decimals_after = len(body) - last - 1
        # One or two digits after the final separator makes it the decimal point; three makes
        # it a thousands separator. That single rule covers every form in the pack:
        #   5,750.00 -> 5750.00   (2 after: decimal)
        #   5.750.00 -> 5750.00   (2 after: decimal, the earlier dot is thousands - this is the
        #                          form tesseract produces where the fold crosses the folio)
        #   1,415.0  -> 1415.00   (1 after: decimal)
        #   5,750    -> 5750.00   (3 after: thousands)
        #   1,00,000 -> 100000.00 (3 after: thousands, Indian lakh grouping)
        if decimals_after in (1, 2):
            digits, fraction = body[:last], body[last + 1 :]
        else:
            digits, fraction = body, ""

    digits = _SEPARATORS.sub("", digits)
    fraction = _SEPARATORS.sub("", fraction)

    if not digits.isdigit() or (fraction and not fraction.isdigit()):
        return None

    try:
        value = Decimal(f"{digits}.{fraction or '0'}").quantize(_PAISE)
    except InvalidOperation:
        return None

    return -value if negative else value
