"""Unit 3: persisting the pack's inbox as evidence. The database half."""

import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.config.settings import settings
from expense_api.db.models import ClaimEvent, DocKind, EvidenceDocument, ExtractionStatus
from expense_api.evidence.store import ingest_directory
from tests.db_helpers import make_employee, make_travel_request

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

EMAILS_DIR = settings.pack_dir / "sample_emails"
RECEIPTS_DIR = settings.pack_dir / "receipts"


async def _ingest(session: AsyncSession, travel_request_id: int | None = None):  # type: ignore[no-untyped-def]
    return await ingest_directory(
        session,
        emails_dir=EMAILS_DIR,
        receipts_dir=RECEIPTS_DIR,
        claimant_email="chaitanya.reddy@nortexindustries.com",
        claimant_name="Chaitanya Reddy",
        travel_request_id=travel_request_id,
    )


async def test_ingests_the_whole_inbox(db_session: AsyncSession) -> None:
    report = await _ingest(db_session)

    assert len(report.documents) == 15
    assert report.failures == {}
    count = (
        await db_session.execute(select(func.count()).select_from(EvidenceDocument))
    ).scalar_one()
    assert count == 15


async def test_doc_kinds_are_persisted_as_classified(db_session: AsyncSession) -> None:
    report = await _ingest(db_session)

    assert report.kind_counts == {
        DocKind.APPROVAL_REQUEST: 1,
        DocKind.APPROVAL_GRANT: 1,
        DocKind.ADVANCE_NOTICE: 1,
        DocKind.FLIGHT_BOOKING: 1,
        DocKind.HOTEL_VOUCHER: 1,
        DocKind.CAB_RECEIPT: 5,
        DocKind.CAB_PAYMENT_FAILURE: 1,
        DocKind.RESTAURANT_BILL: 1,
        DocKind.HOTEL_INVOICE: 1,
        DocKind.THIRD_PARTY_FORWARD: 1,
        DocKind.PROMOTIONAL: 1,
    }


async def test_noise_and_non_receipts_are_stored_but_not_pending(
    db_session: AsyncSession,
) -> None:
    """Kept, so the UI can show they were seen and set aside rather than missed.

    Marked NOT_APPLICABLE rather than PENDING, so they never look like outstanding work.
    """
    await _ingest(db_session)

    for filename in ("14_promo_noise.eml", "08_uber_payment_failed.eml"):
        document = (
            await db_session.execute(
                select(EvidenceDocument).where(EvidenceDocument.source_filename == filename)
            )
        ).scalar_one()
        assert document.extraction_status is ExtractionStatus.NOT_APPLICABLE

    receipt = (
        await db_session.execute(
            select(EvidenceDocument).where(
                EvidenceDocument.source_filename == "09_uber_receipt_3.eml"
            )
        )
    ).scalar_one()
    assert receipt.extraction_status is ExtractionStatus.PENDING


async def test_attachments_are_recorded_against_their_documents(
    db_session: AsyncSession,
) -> None:
    await _ingest(db_session)

    documents = (
        (
            await db_session.execute(
                select(EvidenceDocument).where(EvidenceDocument.attachment_path.is_not(None))
            )
        )
        .scalars()
        .all()
    )

    assert {d.source_filename for d in documents} == {
        "11_dinner_bill.eml",
        "12_hotel_invoice.eml",
    }
    for document in documents:
        assert document.attachment_path is not None
        assert document.attachment_path.endswith(".png")


async def test_reingesting_does_not_duplicate(db_session: AsyncSession) -> None:
    """Keyed on Message-ID. A duplicated document would duplicate every line under it."""
    await _ingest(db_session)
    second = await _ingest(db_session)

    assert second.documents == []
    assert len(second.skipped_existing) == 15
    count = (
        await db_session.execute(select(func.count()).select_from(EvidenceDocument))
    ).scalar_one()
    assert count == 15


async def test_every_document_carries_a_specific_proof_reference(
    db_session: AsyncSession,
) -> None:
    """Template legend line 65. §5.2 returns any claim line without one."""
    await _ingest(db_session)

    documents = (await db_session.execute(select(EvidenceDocument))).scalars().all()

    assert all(d.proof_ref for d in documents)
    assert all("attached mail" not in d.proof_ref.lower() for d in documents)
    # Documents with an attachment point at the attachment, not just the message.
    hotel = next(d for d in documents if d.source_filename == "12_hotel_invoice.eml")
    assert hotel.proof_ref == "12_hotel_invoice.eml#hotel_invoice_1188.png"


async def test_ingestion_is_recorded_in_the_audit_trail(db_session: AsyncSession) -> None:
    employee = await make_employee(db_session, emp_code="NX-4471")
    request = await make_travel_request(db_session, employee=employee)

    await _ingest(db_session, travel_request_id=request.id)

    events = (
        (
            await db_session.execute(
                select(ClaimEvent).where(ClaimEvent.action == "evidence_ingested")
            )
        )
        .scalars()
        .all()
    )

    assert len(events) == 15
    assert all(e.travel_request_id == request.id for e in events)
    # The audit trail records which documents were set aside and why they produce nothing.
    promo = next(e for e in events if e.payload["file"] == "14_promo_noise.eml")
    assert promo.payload["doc_kind"] == "promotional"
    assert promo.payload["produces_claim_lines"] is False


async def test_one_unreadable_message_does_not_abandon_the_rest(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """Fourteen good receipts must still land if the fifteenth is corrupt."""
    for path in EMAILS_DIR.glob("*.eml"):
        shutil.copy(path, tmp_path / path.name)
    (tmp_path / "99_corrupt.eml").write_bytes(b"\xff\xfe not a message at all")

    report = await ingest_directory(
        db_session,
        emails_dir=tmp_path,
        receipts_dir=RECEIPTS_DIR,
        claimant_email="chaitanya.reddy@nortexindustries.com",
        claimant_name="Chaitanya Reddy",
    )

    assert len(report.documents) == 15
    assert "99_corrupt.eml" in report.failures

    failures = (
        (
            await db_session.execute(
                select(ClaimEvent).where(ClaimEvent.action == "evidence_parse_failed")
            )
        )
        .scalars()
        .all()
    )
    assert len(failures) == 1
    assert failures[0].payload["file"] == "99_corrupt.eml"
