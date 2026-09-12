"""Unit 3: ingestion - parsing the pack's mail and resolving its attachments."""

from datetime import datetime
from pathlib import Path

import pytest

from expense_api.config.settings import settings
from expense_api.evidence.ingest import parse_eml

EMAILS_DIR = settings.pack_dir / "sample_emails"
RECEIPTS_DIR = settings.pack_dir / "receipts"


def test_parses_headers_and_body() -> None:
    parsed = parse_eml(EMAILS_DIR / "01_travel_approval_request.eml", receipts_dir=RECEIPTS_DIR)

    assert parsed.sender_email == "chaitanya.reddy@nortexindustries.com"
    assert parsed.sender_name == "Chaitanya Reddy"
    assert parsed.subject == "Travel approval request - Bengaluru - 16 to 20 Jun"
    assert parsed.message_id == "<t-approval-001@nortexindustries.com>"
    assert "Requesting approval for travel to Bengaluru" in parsed.body_text


def test_parses_the_date_with_its_offset() -> None:
    """+0530 matters: a naive datetime would move every trip date by up to half a day."""
    parsed = parse_eml(EMAILS_DIR / "01_travel_approval_request.eml", receipts_dir=RECEIPTS_DIR)

    assert parsed.received_at is not None
    assert parsed.received_at.tzinfo is not None
    assert parsed.received_at.utcoffset() is not None
    assert parsed.received_at.utcoffset().total_seconds() == 5.5 * 3600  # type: ignore[union-attr]
    assert parsed.received_at.replace(tzinfo=None) == datetime(2026, 6, 8, 11, 12, 4)


@pytest.mark.parametrize(
    ("filename", "attachment_name"),
    [
        ("11_dinner_bill.eml", "dinner_bill_18jun.png"),
        ("12_hotel_invoice.eml", "hotel_invoice_1188.png"),
    ],
)
def test_resolves_the_packs_placeholder_attachments(filename: str, attachment_name: str) -> None:
    """The pack's attachments are not base64, whatever the headers claim.

    Both messages declare `Content-Transfer-Encoding: base64`, and the part body is the literal
    text `[ATTACHMENT: see receipts/<name> in this pack]`. A standard MIME parser decodes that
    to nothing, and both receipt images disappear from the claim with no error raised.
    """
    parsed = parse_eml(EMAILS_DIR / filename, receipts_dir=RECEIPTS_DIR)

    assert parsed.attachment_path is not None
    assert parsed.attachment_path.name == attachment_name
    assert parsed.attachment_path.exists()
    assert parsed.attachment_path.stat().st_size > 0


def test_messages_without_attachments_have_none() -> None:
    parsed = parse_eml(EMAILS_DIR / "06_uber_receipt_1.eml", receipts_dir=RECEIPTS_DIR)

    assert parsed.attachment_path is None


def test_a_named_attachment_that_is_missing_from_disk_is_an_error(tmp_path: Path) -> None:
    """Silently dropping it would look identical to a message that never had one."""
    from expense_api.evidence.ingest import AttachmentNotFoundError

    message = tmp_path / "with_missing_attachment.eml"
    message.write_text(
        "From: a@b.c\n"
        "To: d@e.f\n"
        "Subject: Bill\n"
        'Content-Type: multipart/mixed; boundary="=_b"\n'
        "\n"
        "--=_b\n"
        "Content-Type: text/plain\n"
        "\n"
        "See attached.\n"
        "--=_b\n"
        'Content-Type: image/png; name="nope.png"\n'
        'Content-Disposition: attachment; filename="nope.png"\n'
        "\n"
        "[ATTACHMENT: see receipts/nope.png in this pack]\n"
        "--=_b--\n"
    )

    with pytest.raises(AttachmentNotFoundError, match="nope.png"):
        parse_eml(message, receipts_dir=tmp_path)


def test_forwarded_body_is_preserved_for_attribution() -> None:
    """Unit 5 needs the rider name out of message 13's forwarded block to reject it."""
    parsed = parse_eml(EMAILS_DIR / "13_colleague_forward.eml", receipts_dir=RECEIPTS_DIR)

    assert "Thanks for riding, Deepa" in parsed.body_text
    assert parsed.sender_email == "deepa.nair@nortexindustries.com"


def test_every_message_in_the_pack_parses() -> None:
    """Fifteen in, fifteen out. Nothing may be skipped."""
    paths = sorted(EMAILS_DIR.glob("*.eml"))
    assert len(paths) == 15

    parsed = [parse_eml(path, receipts_dir=RECEIPTS_DIR) for path in paths]

    assert len(parsed) == 15
    assert all(p.subject for p in parsed)
    assert all(p.sender_email for p in parsed)
    assert all(p.received_at is not None for p in parsed)
    # Message IDs are what dedup and re-ingestion idempotency key on later.
    assert len({p.message_id for p in parsed}) == 15


def test_proof_ref_names_a_specific_document() -> None:
    """Template legend line 65: a proof ref must point at a document, not "attached mail"."""
    parsed = parse_eml(EMAILS_DIR / "12_hotel_invoice.eml", receipts_dir=RECEIPTS_DIR)

    assert parsed.proof_ref
    assert "attached mail" not in parsed.proof_ref.lower()
    # Identifies the source well enough for Finance to find it again.
    assert "12_hotel_invoice" in parsed.proof_ref
