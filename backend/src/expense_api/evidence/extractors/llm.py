"""Model-based extraction adapter.

**This adapter has never been executed.** There is no API credential in the environment this
was built in - no ANTHROPIC_API_KEY, no `ant` CLI, no OAuth profile - so it has not been run
against the real API even once. It is a seam with a concrete implementation behind it, not a
tested feature, and the note says so too. Do not present it as working.

Why it exists anyway: the rule-based parsers are tuned to the sender formats in this pack and
will not read an unseen vendor. That is the real limitation of the shipped path, and this is
the shape of the fix - same protocol, same output, so dedup, policy and workflow are untouched.
The reconciliation guard runs underneath this adapter exactly as it does under the other one,
which matters more here: a model that misreads a folio line fails the same check.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from expense_api.config.settings import settings
from expense_api.db.models import DocKind
from expense_api.evidence.extractors.base import (
    ExtractedItem,
    ExtractionResult,
    from_items,
    needs_input,
)
from expense_api.evidence.ingest import ParsedEmail

logger = logging.getLogger(__name__)

NAME = "llm"

MODEL = "claude-opus-5"

# Anything the model is less sure of than this becomes a needs-input prompt rather than a
# pre-filled value. Uncalibrated - it needs real output to tune against, which needs a key.
CONFIDENCE_THRESHOLD = 0.7

_SYSTEM = """\
You extract line items from Indian travel expense receipts for a reimbursement system.

Rules that matter more than completeness:
- Report only what the document actually says. Never infer, average, or fill a gap.
- Decompose consolidated bills into individual charge lines. A hotel folio has separate room,
  laundry, mini bar and dining lines, and each is treated differently by policy.
- Report the bill's own stated subtotal and total verbatim when present. They are checked
  against the sum of your line items, so a guessed figure will be caught and will waste a
  person's time.
- If a line is illegible, say so in `unreadable_lines` rather than omitting it silently. A
  missing line is worse than a flagged one.
- Amounts are Indian format and may be OCR-damaged: 5.750.00 means 5750.00.
"""

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "gross_amount": {"type": "string"},
                    "merchant": {"type": ["string", "null"]},
                    "txn_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                    "tax_amount": {"type": ["string", "null"]},
                    "payment_method": {"type": ["string", "null"]},
                    "payer_name": {"type": ["string", "null"]},
                    "bill_no": {"type": ["string", "null"]},
                    "nights": {"type": ["integer", "null"]},
                    "confidence": {"type": "number"},
                },
                "required": ["description", "gross_amount", "confidence"],
                "additionalProperties": False,
            },
        },
        "stated_subtotal": {"type": ["string", "null"]},
        "stated_total": {"type": ["string", "null"]},
        "unreadable_lines": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["line_items", "unreadable_lines"],
    "additionalProperties": False,
}


class LlmCredentialsMissingError(RuntimeError):
    """Selected without anything to authenticate with."""


class LlmExtractor:
    name = NAME

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            # Fail at construction, not mid-run. Selecting this adapter without a credential is
            # a configuration mistake, and it should look like one immediately.
            raise LlmCredentialsMissingError(
                "EXTRACTOR=llm requires ANTHROPIC_API_KEY. The rule-based adapter is the "
                "default and needs no credentials."
            )

    def extract(self, parsed: ParsedEmail, kind: DocKind) -> ExtractionResult:
        try:
            payload = self._call(parsed, kind)
        except Exception as exc:  # noqa: BLE001 - any failure falls back to a human
            logger.warning("LLM extraction failed for %s: %s", parsed.source_filename, exc)
            return needs_input(NAME, f"Model extraction failed: {exc}")

        items: list[ExtractedItem] = []
        for raw in payload.get("line_items", []):
            item = _to_item(raw)
            if item is not None:
                items.append(item)

        unreadable = payload.get("unreadable_lines") or []
        if unreadable:
            return needs_input(
                NAME,
                "The model could not read: " + "; ".join(unreadable),
                items=items,
                stated_subtotal=_decimal(payload.get("stated_subtotal")),
            )

        low = [i for i in items if i.confidence < CONFIDENCE_THRESHOLD]
        if low:
            return needs_input(
                NAME,
                f"{len(low)} line(s) below the confidence threshold; please confirm the amounts",
                items=items,
                stated_subtotal=_decimal(payload.get("stated_subtotal")),
            )

        return from_items(
            NAME,
            items,
            stated_subtotal=_decimal(payload.get("stated_subtotal")),
            stated_total=_decimal(payload.get("stated_total")),
        )

    def _call(self, parsed: ParsedEmail, kind: DocKind) -> dict[str, Any]:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        content: list[dict[str, Any]] = []
        if parsed.attachment_path is not None:
            import base64

            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.standard_b64encode(
                            parsed.attachment_path.read_bytes()
                        ).decode(),
                    },
                }
            )
        content.append(
            {
                "type": "text",
                "text": (
                    f"Document kind: {kind.value}\nSubject: {parsed.subject}\n\n{parsed.body_text}"
                ),
            }
        )

        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=_SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )

        import json

        text = "".join(block.text for block in response.content if block.type == "text")
        return dict(json.loads(text))


def _to_item(raw: dict[str, Any]) -> ExtractedItem | None:
    amount = _decimal(raw.get("gross_amount"))
    if amount is None:
        return None

    from datetime import date

    txn_date = None
    if raw.get("txn_date"):
        try:
            txn_date = date.fromisoformat(str(raw["txn_date"]))
        except ValueError:
            txn_date = None

    return ExtractedItem(
        gross_amount=amount,
        description=str(raw.get("description") or "Unlabelled charge"),
        merchant=raw.get("merchant"),
        txn_date=txn_date,
        tax_amount=_decimal(raw.get("tax_amount")),
        payment_method=raw.get("payment_method"),
        payer_name=raw.get("payer_name"),
        bill_no=raw.get("bill_no"),
        nights=raw.get("nights"),
        confidence=float(raw.get("confidence", 0.0)),
    )


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
