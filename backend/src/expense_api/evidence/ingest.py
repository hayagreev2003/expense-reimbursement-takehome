"""Parse `.eml` files into a structure the rest of the pipeline can work with.

Attachments are the one non-obvious part, because the two message forms this reads carry them
differently and everything downstream wants the same thing - a path on disk.

**The pack's form.** Messages 11 and 12 declare `Content-Transfer-Encoding: base64`, but the
part body is the literal text `[ATTACHMENT: see receipts/<name> in this pack]`. A standard MIME
parser decodes that to nothing and both receipt images vanish from the claim with no error
raised - so the parser recognises the placeholder and resolves the named file against
`pack/receipts/`.

**A real mailbox's form.** The part carries the encoded bytes. Those are written out to
`extract_dir` under a name derived from the message, and the path is what the rest of the
pipeline sees. Nothing downstream can read bytes: the OCR adapter and the LLM adapter both take
a path, so a message whose attachment was never written out is a message whose receipt is
silently missing - which is exactly what used to happen here.

The name is derived from the message rather than randomised because a draft claim is recomputed
from its evidence on every read, so this parses the same file many times and must find what it
wrote last time instead of accumulating copies.
"""

from __future__ import annotations

import email
import email.policy
import logging
import mimetypes
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


# Parts that are never the bill. A signature block has a filename and would otherwise be
# written out and handed to the extractor as if it were a receipt.
_NEVER_ATTACHMENT = frozenset(
    {"application/pgp-signature", "application/pkcs7-signature", "application/pkcs7-mime"}
)

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

# Used to give a nameless part a plausible extension when the Content-Type does not.
_SIGNATURE_SUFFIXES = ((b"\x89PNG", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"%PDF", ".pdf"))


# `[ATTACHMENT: see receipts/dinner_bill_18jun.png in this pack]`
_PLACEHOLDER = re.compile(r"\[ATTACHMENT:\s*see\s+(?:receipts/)?(?P<name>[\w.\-]+)", re.I)


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
    # Every attachment, in the order the message carried them. A real mail can attach two
    # pages of one folio, and keeping only the first would drop half a bill.
    attachment_paths: tuple[Path, ...]
    proof_ref: str

    @property
    def attachment_path(self) -> Path | None:
        """The attachment, for the single-document case that most callers are."""
        return self.attachment_paths[0] if self.attachment_paths else None

    @property
    def is_forward(self) -> bool:
        subject = (self.subject or "").lower()
        return subject.startswith(("fwd:", "fw:")) or "forwarded message" in self.body_text.lower()


def parse_eml(path: Path, *, receipts_dir: Path, extract_dir: Path | None = None) -> ParsedEmail:
    """One message, parsed.

    `receipts_dir` is where a placeholder's named file is looked up. `extract_dir` is where a
    real MIME attachment's bytes get written; it defaults to the message's own directory, which
    is right for an upload and wrong for the pack - `pack/` is mounted read-only, so a caller
    reading pack mail passes a writable directory instead.
    """
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

    attachment_paths = _resolve_attachments(message, path, receipts_dir, extract_dir or path.parent)

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
        attachment_paths=attachment_paths,
        proof_ref=_proof_ref(path, attachment_paths),
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


def _resolve_attachments(
    message: EmailMessage, source: Path, receipts_dir: Path, extract_dir: Path
) -> tuple[Path, ...]:
    resolved: list[Path] = []

    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if not _is_attachment(part):
            continue

        decoded = part.get_payload(decode=True)
        raw = decoded if isinstance(decoded, bytes) else None

        # The pack's placeholder, which names a file that is already on disk.
        placeholder = _placeholder_name(part, raw)
        if placeholder is not None:
            candidate = receipts_dir / placeholder
            if not candidate.exists():
                raise AttachmentNotFoundError(
                    f"{source.name} names attachment {placeholder!r}, which is not in "
                    f"{receipts_dir}"
                )
            resolved.append(candidate)
            continue

        # A real part: the bytes are the attachment, so write them where the extractor can
        # reach them. An OSError here (a read-only directory) is left to the caller, which
        # surfaces it as needs-input rather than losing the document.
        if raw:
            resolved.append(_materialise(raw, part, source, extract_dir))

    # Two parts of the same message can name the same file; dict.fromkeys keeps first order.
    return tuple(dict.fromkeys(resolved))


def _is_attachment(part: EmailMessage) -> bool:
    """Whether this part is a document rather than the message body.

    An inline image counts: a mailed bill is routinely sent `Content-Disposition: inline` with
    a `cid:` reference, and refusing those would drop the receipt on a large share of real mail.
    """
    if part.get_content_type() in _NEVER_ATTACHMENT:
        return False
    if part.get_filename():
        return True
    if "attachment" in (part.get("Content-Disposition") or "").lower():
        return True
    return part.get_content_maintype() == "image"


def _placeholder_name(part: EmailMessage, raw: bytes | None) -> str | None:
    """The filename inside the pack's `[ATTACHMENT: ...]` text, if that is what this part is."""
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else ""
    match = _PLACEHOLDER.search(text)
    if match is None:
        # The placeholder is declared base64 and does not decode, so the undecoded payload has
        # to be checked too.
        payload = part.get_payload()
        match = _PLACEHOLDER.search(payload) if isinstance(payload, str) else None
    return match.group("name") if match else None


def _materialise(raw: bytes, part: EmailMessage, source: Path, extract_dir: Path) -> Path:
    """Write one real attachment beside its message, once."""
    target = extract_dir / f"{source.stem}--{_attachment_name(part, raw)}"
    if target.exists() and target.stat().st_size == len(raw):
        return target

    extract_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    logger.debug("Extracted %s from %s", target.name, source.name)
    return target


def _attachment_name(part: EmailMessage, raw: bytes) -> str:
    """A safe filename for a part, whether or not it declared one.

    `Path(...).name` runs before the character allowlist, so a part claiming `../../x.png`
    cannot escape `extract_dir`; sanitising first would turn `../x` into `..x` and keep the
    traversal.
    """
    declared = Path(part.get_filename() or "").name
    cleaned = _UNSAFE_NAME.sub("_", declared).strip("._")[:120]
    if cleaned and Path(cleaned).suffix:
        return cleaned

    suffix = next(
        (ext for signature, ext in _SIGNATURE_SUFFIXES if raw.startswith(signature)),
        mimetypes.guess_extension(part.get_content_type()) or ".bin",
    )
    return f"{cleaned or 'attachment'}{suffix}"


def _proof_ref(source: Path, attachments: tuple[Path, ...]) -> str:
    """Names a specific document, never "attached mail" (template legend line 65)."""
    if attachments:
        return f"{source.name}#{'+'.join(a.name for a in attachments)}"
    return source.name
