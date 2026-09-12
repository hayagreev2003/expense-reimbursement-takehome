"""Parse the pack's `.eml` files into a structure the rest of the pipeline can work with.

The one non-obvious part is attachments. Messages 11 and 12 declare
`Content-Transfer-Encoding: base64`, but the part body is the literal text
`[ATTACHMENT: see receipts/<name> in this pack]`. A standard MIME parser decodes that to
nothing and both receipt images vanish from the claim with no error raised - so the parser has
to recognise the placeholder and resolve the named file against `pack/receipts/`.

Real base64 parts are handled too, so this is not pack-specific.
"""

from __future__ import annotations

import email
import email.policy
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class EmailParseError(Exception):
    """The file is not a message we can make sense of."""


class AttachmentNotFoundError(Exception):
    """A part named an attachment that is not on disk.

    Raised rather than logged: a dropped attachment is indistinguishable from a message that
    never had one, and one of them is a missing claim line.
    """


# `[ATTACHMENT: see receipts/dinner_bill_18jun.png in this pack]`
_PLACEHOLDER = re.compile(r"\[ATTACHMENT:\s*see\s+(?:receipts/)?(?P<name>[\w.\-]+)", re.I)

# PNG, JPEG, PDF. Used to tell a genuinely encoded part from the placeholder text.
_BINARY_SIGNATURES = (b"\x89PNG", b"\xff\xd8\xff", b"%PDF")


@dataclass(frozen=True, slots=True)
class ParsedEmail:
    """One message, flattened. No interpretation yet - that is classify()'s job."""

    source_path: Path
    source_filename: str
    message_id: str | None
    sender_name: str | None
    sender_email: str | None
    recipients: tuple[str, ...]
    subject: str | None
    received_at: datetime | None
    body_text: str
    attachment_path: Path | None
    proof_ref: str

    @property
    def is_forward(self) -> bool:
        subject = (self.subject or "").lower()
        return subject.startswith(("fwd:", "fw:")) or "forwarded message" in self.body_text.lower()


def parse_eml(path: Path, *, receipts_dir: Path) -> ParsedEmail:
    try:
        raw = path.read_bytes()
        message = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception as exc:  # noqa: BLE001 - anything here means the file is unusable
        raise EmailParseError(f"Could not parse {path.name}: {exc}") from exc

    if not isinstance(message, EmailMessage):  # pragma: no cover - policy.default guarantees it
        raise EmailParseError(f"Unexpected message type for {path.name}")

    sender_name, sender_email = parseaddr(_header(message, "From"))

    # A message with no From and no Subject is not a message; it is a file that happened to
    # survive the parser. Fail rather than emit an empty document.
    if not sender_email and not _header(message, "Subject"):
        raise EmailParseError(f"{path.name} has neither a From nor a Subject header")

    attachment_path = _resolve_attachment(message, path, receipts_dir)

    return ParsedEmail(
        source_path=path,
        source_filename=path.name,
        message_id=_header(message, "Message-ID") or None,
        sender_name=sender_name or None,
        sender_email=sender_email.lower() or None,
        recipients=_recipients(message),
        subject=_header(message, "Subject") or None,
        received_at=_received_at(message, path.name),
        body_text=_body_text(message),
        attachment_path=attachment_path,
        proof_ref=_proof_ref(path, attachment_path),
    )


def _header(message: EmailMessage, name: str) -> str:
    value = message.get(name)
    return str(value).strip() if value is not None else ""


def _recipients(message: EmailMessage) -> tuple[str, ...]:
    addresses: list[str] = []
    for field in ("To", "Cc"):
        raw = _header(message, field)
        if not raw:
            continue
        for part in raw.split(","):
            _, address = parseaddr(part)
            if address:
                addresses.append(address.lower())
    return tuple(addresses)


def _received_at(message: EmailMessage, filename: str) -> datetime | None:
    raw = _header(message, "Date")
    if not raw:
        return None
    try:
        # parsedate_to_datetime keeps the +0530 offset. Dropping it would shift trip dates by
        # up to half a day, which is enough to move an expense onto the wrong travel day.
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        logger.warning("Unparseable Date header in %s: %r", filename, raw)
        return None


def _body_text(message: EmailMessage) -> str:
    """Every text/plain part, in order, including forwarded blocks.

    Forwarded content is kept rather than stripped: the rider name inside message 13's
    forwarded block is exactly what attribution needs to reject it.
    """
    chunks: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_type() != "text/plain":
            continue
        if part.get_filename():  # a text file attachment, not the body
            continue
        try:
            chunks.append(part.get_content())
        except (LookupError, UnicodeDecodeError):
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                chunks.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(chunk.strip() for chunk in chunks if chunk).strip()


def _resolve_attachment(message: EmailMessage, source: Path, receipts_dir: Path) -> Path | None:
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue

        filename = part.get_filename()
        disposition = (part.get("Content-Disposition") or "").lower()
        if not filename and "attachment" not in disposition:
            continue

        raw = part.get_payload(decode=True)

        # A genuinely encoded binary part: trust it and leave it where it is. Nothing in the
        # pack takes this branch, but a real mailbox would.
        if isinstance(raw, bytes) and raw.startswith(_BINARY_SIGNATURES):
            logger.debug("%s carries an inline binary attachment", source.name)
            return None

        # Otherwise look for the pack's placeholder, falling back to the declared filename.
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else ""
        match = _PLACEHOLDER.search(text) or _PLACEHOLDER.search(str(part.get_payload()))
        name = match.group("name") if match else filename

        if not name:
            continue

        candidate = receipts_dir / name
        if not candidate.exists():
            raise AttachmentNotFoundError(
                f"{source.name} names attachment {name!r}, which is not in {receipts_dir}"
            )
        return candidate

    return None


def _proof_ref(source: Path, attachment: Path | None) -> str:
    """Names a specific document, never "attached mail" (template legend line 65)."""
    if attachment is not None:
        return f"{source.name}#{attachment.name}"
    return source.name
