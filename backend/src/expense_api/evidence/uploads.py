"""Taking a bill the employee uploads and turning it into evidence.

The pack's inbox is the demo's starting point, not the product. In real use the employee has a
photograph of a bill on their phone, or a receipt mail their travel desk never copied anyone
on, and it has to be able to get into the claim.

Two constraints shaped this:

**Nothing is written into `pack/`.** The pack is the specification and its Docker mount is
read-only. Uploads land under `settings.upload_dir`, and the row records where the file went,
so the pipeline can find it again without a directory convention it has to guess at.

**One extraction path, not two.** An uploaded image is wrapped in a message envelope on disk -
a real `.eml` file carrying the pack's own attachment-placeholder form - so it reaches the
extractor exactly as a mailed receipt does. Writing a second "images only" branch through
classify, dedup and reconcile would double the surface that has to stay correct, and it is the
branch that would rot.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.config.settings import settings
from expense_api.db.models import (
    ClaimEvent,
    DocKind,
    Employee,
    EvidenceDocument,
    TravelRequest,
)
from expense_api.evidence.classify import classify
from expense_api.evidence.ingest import (
    AttachmentNotFoundError,
    EmailParseError,
    parse_eml,
)
from expense_api.evidence.store import to_document

logger = logging.getLogger(__name__)

# Allowlist, never a denylist of "dangerous" extensions. Anything not named here is refused.
# A phone photograph (.png/.jpg/.webp) or a scanned/text receipt (.pdf): both are bills the
# extractor reads from the attachment, so both take the same declared-kind path.
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".pdf"})
MAIL_SUFFIXES = frozenset({".eml"})
ALLOWED_SUFFIXES = IMAGE_SUFFIXES | MAIL_SUFFIXES

# The kinds an employee may declare for a photographed bill. Deliberately only the four the
# extractor has a parser for: offering a kind nothing can read produces a document that sits in
# needs-input forever and looks like a bug.
DECLARABLE_KINDS: tuple[DocKind, ...] = (
    DocKind.HOTEL_INVOICE,
    DocKind.RESTAURANT_BILL,
    DocKind.CAB_RECEIPT,
    DocKind.FLIGHT_BOOKING,
)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class UploadRejected(Exception):
    """The file cannot become evidence, and saying why is more useful than storing it."""


@dataclass(frozen=True, slots=True)
class UploadResult:
    document: EvidenceDocument
    stored_path: Path


def safe_name(filename: str) -> str:
    """A filename that cannot escape the upload directory or collide with a shell.

    `Path(...).name` strips any directory component, including `../`, before the character
    allowlist runs - order matters, since sanitising first would turn `../x` into `..x`.
    """
    base = Path(filename or "").name
    cleaned = _UNSAFE.sub("_", base).strip("._") or "upload"
    return cleaned[:120]


def upload_dir_for(trq_id: str) -> Path:
    return settings.upload_dir / safe_name(trq_id)


def _unique_path(directory: Path, name: str) -> Path:
    """Never overwrite. Two photographs of different bills routinely share a camera filename."""
    candidate = directory / name
    if not candidate.exists():
        return candidate

    stem, suffix = candidate.stem, candidate.suffix
    for counter in range(1, 1000):
        alternative = directory / f"{stem}-{counter}{suffix}"
        if not alternative.exists():
            return alternative
    raise UploadRejected("Too many files with that name already exist.")


def _envelope_for_image(
    *, image_path: Path, claimant: Employee, kind: DocKind, note: str | None
) -> bytes:
    """Wrap an uploaded image in the message form the rest of the pipeline already reads."""
    message = EmailMessage()
    message["From"] = f"{claimant.name} <{claimant.email}>"
    message["To"] = claimant.email
    message["Subject"] = f"Uploaded {kind.value.replace('_', ' ')}: {image_path.name}"
    message["Date"] = format_datetime(datetime.now(UTC))
    message["Message-ID"] = f"<upload-{uuid.uuid4()}@nortex.local>"

    body = note.strip() if note and note.strip() else ""
    message.set_content(
        f"{body}\n\nUploaded by {claimant.name} ({claimant.emp_code}).".strip()
        if body
        else f"Uploaded by {claimant.name} ({claimant.emp_code})."
    )
    # The placeholder form, not the bytes: the image is already on disk beside this file, and
    # _resolve_attachment reads the placeholder and returns that path.
    message.add_attachment(
        f"[ATTACHMENT: see {image_path.name} in this pack]".encode(),
        maintype="application",
        subtype="octet-stream",
        filename=image_path.name,
    )
    return bytes(message.as_bytes())


async def store_upload(
    session: AsyncSession,
    *,
    travel_request: TravelRequest,
    claimant: Employee,
    filename: str,
    content: bytes,
    declared_kind: DocKind | None = None,
    note: str | None = None,
) -> UploadResult:
    """Persist one uploaded file as an EvidenceDocument attached to this trip."""
    if not content:
        raise UploadRejected("That file is empty.")
    if len(content) > settings.max_upload_bytes:
        raise UploadRejected(
            f"That file is larger than {settings.max_upload_bytes // (1024 * 1024)} MB."
        )

    name = safe_name(filename)
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise UploadRejected(
            "Upload a receipt image (.png, .jpg, .webp, .pdf) or a forwarded mail (.eml). "
            f"{suffix or 'That file'} is not readable as evidence."
        )

    directory = upload_dir_for(travel_request.trq_id)
    directory.mkdir(parents=True, exist_ok=True)

    if suffix in IMAGE_SUFFIXES:
        if declared_kind is None:
            # A photograph carries no sender and no subject, so classification has nothing to
            # work from. Asking is better than guessing: the wrong kind silently selects the
            # wrong parser and the amounts come out plausible and wrong.
            raise UploadRejected("Tell us what this bill is before uploading it.")
        if declared_kind not in DECLARABLE_KINDS:
            raise UploadRejected(f"{declared_kind.value} cannot be read from an image.")

        image_path = _unique_path(directory, name)
        image_path.write_bytes(content)
        mail_path = _unique_path(directory, f"{image_path.stem}.eml")
        mail_path.write_bytes(
            _envelope_for_image(
                image_path=image_path, claimant=claimant, kind=declared_kind, note=note
            )
        )
    else:
        mail_path = _unique_path(directory, name)
        mail_path.write_bytes(content)

    try:
        parsed = parse_eml(mail_path, receipts_dir=directory)
    except AttachmentNotFoundError as exc:
        # A forwarded mail whose attachment did not come with it. The mail is unusable on its
        # own, so it is refused rather than stored as evidence with nothing behind it.
        mail_path.unlink(missing_ok=True)
        raise UploadRejected(
            "That mail names an attachment that was not uploaded with it. "
            "Upload the receipt image itself."
        ) from exc
    except (EmailParseError, OSError) as exc:
        mail_path.unlink(missing_ok=True)
        raise UploadRejected(f"That file could not be read as a message: {exc}") from exc

    kind = declared_kind or classify(
        parsed, claimant_email=claimant.email, claimant_name=claimant.name
    )
    document = to_document(parsed, kind, travel_request.id, source_path=str(mail_path))
    session.add(document)

    session.add(
        ClaimEvent(
            travel_request_id=travel_request.id,
            actor_employee_id=claimant.id,
            action="evidence_uploaded",
            payload={
                "file": parsed.source_filename,
                "doc_kind": kind.value,
                "proof_ref": parsed.proof_ref,
                "declared": declared_kind is not None,
            },
        )
    )
    await session.flush()

    logger.info("Stored upload %s for %s as %s", name, travel_request.trq_id, kind.value)
    return UploadResult(document=document, stored_path=mail_path)


async def delete_upload(session: AsyncSession, *, document: EvidenceDocument) -> None:
    """Remove an uploaded document and the file behind it.

    Only ever called for a document the employee uploaded themselves and only while the claim
    is still a draft - the caller enforces both. Nothing that has been through an approval is
    removable, because an approver signed off on a set of evidence and that set has to survive.
    """
    if document.source_path:
        path = Path(document.source_path)
        attachment = Path(document.attachment_path) if document.attachment_path else None
        path.unlink(missing_ok=True)
        if attachment is not None and attachment.is_relative_to(settings.upload_dir):
            attachment.unlink(missing_ok=True)

    session.add(
        ClaimEvent(
            travel_request_id=document.travel_request_id,
            action="evidence_upload_removed",
            payload={"file": document.source_filename, "proof_ref": document.proof_ref},
        )
    )
    await session.delete(document)
    await session.flush()
