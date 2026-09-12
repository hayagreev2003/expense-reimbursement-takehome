"""Persist parsed mail as EvidenceDocument rows.

Idempotent on Message-ID, so re-ingesting a mailbox does not duplicate evidence - which in turn
would duplicate claim lines that dedup then has to unpick.

Documents that will never produce a claim line are still stored, with their extraction status
set to NOT_APPLICABLE. The promotional mail and the payment-failure notice have to be visible
as "seen and set aside", because an item that is simply absent looks exactly like one that was
missed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.db.models import (
    ClaimEvent,
    DocKind,
    EvidenceDocument,
    ExtractionStatus,
)
from expense_api.evidence.classify import classify, produces_claim_lines
from expense_api.evidence.ingest import EmailParseError, ParsedEmail, parse_eml

logger = logging.getLogger(__name__)


@dataclass
class IngestReport:
    documents: list[EvidenceDocument] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def kind_counts(self) -> dict[DocKind, int]:
        counts: dict[DocKind, int] = {}
        for document in self.documents:
            counts[document.doc_kind] = counts.get(document.doc_kind, 0) + 1
        return counts


async def ingest_directory(
    session: AsyncSession,
    *,
    emails_dir: Path,
    receipts_dir: Path,
    claimant_email: str,
    claimant_name: str,
    travel_request_id: int | None = None,
) -> IngestReport:
    report = IngestReport()

    existing_ids = set((await session.execute(select(EvidenceDocument.message_id))).scalars().all())

    for path in sorted(emails_dir.glob("*.eml")):
        try:
            parsed = parse_eml(path, receipts_dir=receipts_dir)
        except (EmailParseError, OSError) as exc:
            # One unreadable message must not abandon the other fourteen. Record it so the
            # employee can see something arrived and could not be read.
            logger.warning("Skipping %s: %s", path.name, exc)
            report.failures[path.name] = str(exc)
            session.add(
                ClaimEvent(
                    travel_request_id=travel_request_id,
                    action="evidence_parse_failed",
                    payload={"file": path.name, "error": str(exc)},
                )
            )
            continue

        if parsed.message_id and parsed.message_id in existing_ids:
            report.skipped_existing.append(path.name)
            continue

        kind = classify(parsed, claimant_email=claimant_email, claimant_name=claimant_name)
        document = to_document(parsed, kind, travel_request_id)
        session.add(document)
        report.documents.append(document)
        if parsed.message_id:
            existing_ids.add(parsed.message_id)

        session.add(
            ClaimEvent(
                travel_request_id=travel_request_id,
                action="evidence_ingested",
                payload={
                    "file": parsed.source_filename,
                    "doc_kind": kind.value,
                    "proof_ref": parsed.proof_ref,
                    "produces_claim_lines": produces_claim_lines(kind),
                },
            )
        )

    await session.flush()
    logger.info(
        "Ingested %d documents (%d already present, %d unreadable)",
        len(report.documents),
        len(report.skipped_existing),
        len(report.failures),
    )
    return report


def to_document(
    parsed: ParsedEmail,
    kind: DocKind,
    travel_request_id: int | None,
    *,
    source_path: str | None = None,
) -> EvidenceDocument:
    """One parsed message as a row.

    `source_path` is set for anything that does not live in the pack's own mail directory - an
    employee upload - so the pipeline can find the file again without guessing at a directory.
    """
    return EvidenceDocument(
        travel_request_id=travel_request_id,
        source_filename=parsed.source_filename,
        source_path=source_path,
        message_id=parsed.message_id,
        sender=parsed.sender_email,
        subject=parsed.subject,
        received_at=parsed.received_at,
        body_text=parsed.body_text,
        attachment_path=str(parsed.attachment_path) if parsed.attachment_path else None,
        doc_kind=kind,
        # Nothing that cannot produce a claim line is left looking like pending work.
        extraction_status=(
            ExtractionStatus.PENDING
            if produces_claim_lines(kind)
            else ExtractionStatus.NOT_APPLICABLE
        ),
        proof_ref=parsed.proof_ref,
    )
