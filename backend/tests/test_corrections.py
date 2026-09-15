"""Correcting a bill nothing could read.

`needs_input` blocks submission on purpose - an unbalanced document must not become claim lines
on a guess. Before this flow existed that block had no exit: the only move left was to delete the
bill and upload the same unreadable image again. These tests pin the exit, and the four things
that keep it from being a hole - policy still applies to what was typed, a second correction
replaces the first rather than adding to it, the figures have to add up to the total on the bill,
and a document that *was* read cannot be overwritten by hand.
"""

from __future__ import annotations

import io

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.db.models import ClaimEvent, TravelRequest

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

CLAIMANT = "NX-4471"  # Chaitanya Reddy, the traveller
OTHER_EMPLOYEE = "NX-4490"  # Imran Qureshi, uninvolved
TRQ = "TRQ-2026-0001"


def _as(emp_code: str) -> dict[str, str]:
    return {"X-Emp-Code": emp_code}


def _blank_png() -> bytes:
    """A photograph with nothing legible on it. The realistic failure: a dark, folded bill."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (400, 220), "white").save(buffer, format="PNG")
    return buffer.getvalue()


async def _unreadable_folio(client: AsyncClient) -> tuple[str, str]:
    """Upload an unreadable hotel folio; return its external id and the name it is filed under.

    The name is asked for rather than assumed: an uploaded image is stored inside an envelope
    message, and the envelope is what the pipeline and the claim refer to.
    """
    response = await client.post(
        f"/api/v1/trips/{TRQ}/documents",
        files={"file": ("folio_scan.png", _blank_png(), "image/png")},
        data={"doc_kind": "hotel_invoice"},
        headers=_as(CLAIMANT),
    )
    assert response.status_code == 201, response.text
    document = response.json()["document"]
    return str(document["external_id"]), str(document["source_filename"])


def _correction(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "lines": [
            {
                "description": "Scanned folio: room tariff",
                "gross_amount": "15000.00",
                "txn_date": "2026-06-16",
                "merchant": "Lemon Tree Premier",
                "bill_no": "LT/1188",
                "nights": 3,
                "paid_by": "Employee",
            },
            {
                "description": "Scanned folio: laundry",
                "gross_amount": "450.00",
                "txn_date": "2026-06-18",
                "merchant": "Lemon Tree Premier",
                "paid_by": "Employee",
            },
        ]
    }
    body.update(overrides)
    return body


# ------------------------------------------------------------------ the exit


async def test_a_bill_nothing_could_read_becomes_claim_lines_once_corrected(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    external_id, filename = await _unreadable_folio(api_client)

    blocked = await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(CLAIMANT))
    assert filename in [entry["source_filename"] for entry in blocked.json()["needs_input"]]

    corrected = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents/{external_id}/correction",
        json=_correction(),
        headers=_as(CLAIMANT),
    )

    assert corrected.status_code == 200, corrected.text
    claim = corrected.json()

    descriptions = [line["description"] for line in claim["lines"]]
    assert "Scanned folio: room tariff" in descriptions
    assert "Scanned folio: laundry" in descriptions

    # No longer blocking, and the claim says whose figures these are.
    assert filename not in [entry["source_filename"] for entry in claim["needs_input"]]
    assert filename in [entry["source_filename"] for entry in claim["manually_entered"]]


async def test_policy_still_applies_to_a_figure_that_was_typed(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """A correction changes what the numbers are, never what policy makes of them.

    §4 disallows laundry by name, and it is disallowed here exactly as it would be on a folio
    the extractor read - with the amount visible and the clause cited, not dropped.
    """
    external_id, filename = await _unreadable_folio(api_client)

    claim = (
        await api_client.post(
            f"/api/v1/trips/{TRQ}/documents/{external_id}/correction",
            json=_correction(),
            headers=_as(CLAIMANT),
        )
    ).json()

    laundry = next(
        line for line in claim["lines"] if line["description"] == "Scanned folio: laundry"
    )
    assert laundry["disallowed_amount"] == "450.00"
    assert laundry["allowed_amount"] == "0.00"
    assert any("§4" in decision["citation"] for decision in laundry["decisions"])


async def test_a_corrected_folio_is_measured_per_night_not_per_bill(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """§3.1 is a per-night limit, so the nights the claimant entered have to reach the rule.

    Bengaluru is Tier 1: 6,000 a night. 21,000 over three nights is 7,000 a night, so 1,000 a
    night is disallowed - not the 15,000 that a bill read as a single night would lose.
    """
    external_id, filename = await _unreadable_folio(api_client)

    claim = (
        await api_client.post(
            f"/api/v1/trips/{TRQ}/documents/{external_id}/correction",
            json={
                "lines": [
                    {
                        "description": "Scanned folio: room tariff",
                        "gross_amount": "21000.00",
                        "txn_date": "2026-06-16",
                        "nights": 3,
                    }
                ]
            },
            headers=_as(CLAIMANT),
        )
    ).json()

    room = next(
        line for line in claim["lines"] if line["description"] == "Scanned folio: room tariff"
    )
    assert room["disallowed_amount"] == "3000.00"
    assert room["allowed_amount"] == "18000.00"


# ------------------------------------------------------------- the safeguards


async def test_a_second_correction_replaces_the_first_rather_than_doubling_the_bill(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    external_id, filename = await _unreadable_folio(api_client)

    await api_client.post(
        f"/api/v1/trips/{TRQ}/documents/{external_id}/correction",
        json=_correction(),
        headers=_as(CLAIMANT),
    )
    again = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents/{external_id}/correction",
        json={
            "lines": [
                {
                    "description": "Scanned folio: room tariff",
                    "gross_amount": "15000.00",
                    "txn_date": "2026-06-16",
                    "nights": 3,
                }
            ]
        },
        headers=_as(CLAIMANT),
    )

    assert again.status_code == 200, again.text
    lines = again.json()["lines"]
    assert [line["description"] for line in lines].count("Scanned folio: room tariff") == 1
    # The line the first correction added is gone, not still standing beside the new one.
    assert "Scanned folio: laundry" not in [line["description"] for line in lines]


async def test_lines_that_do_not_add_up_to_the_stated_total_are_refused(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """The same discipline the reconciliation guard applies to a document that was read."""
    external_id, filename = await _unreadable_folio(api_client)

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents/{external_id}/correction",
        json=_correction(stated_total="19200.00"),
        headers=_as(CLAIMANT),
    )

    assert response.status_code == 422
    # `{code, message}` rather than a Pydantic error array: the array echoes the submitted
    # values, so the client cannot render it and shows a generic message instead - which hides
    # the one number the claimant has to see.
    detail = response.json()["detail"]
    assert detail["code"] == "total_mismatch"
    assert "15450.00" in detail["message"]  # what was typed
    assert "19200.00" in detail["message"]  # what the bill says


async def test_a_document_that_was_read_cleanly_cannot_be_overwritten_by_hand(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """Overwriting a balanced extraction is not a correction, it is an unreviewed edit."""
    await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(CLAIMANT))

    documents = (
        await api_client.get(f"/api/v1/trips/{TRQ}/documents", headers=_as(CLAIMANT))
    ).json()
    cab = next(
        document for document in documents if document["source_filename"] == "06_uber_receipt_1.eml"
    )
    assert cab["extraction_status"] == "extracted"
    assert cab["correctable"] is False

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents/{cab['external_id']}/correction",
        json=_correction(),
        headers=_as(CLAIMANT),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_read"


async def test_a_promotional_mail_cannot_be_corrected_into_a_claim_line(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """The set-aside documents are not evidence of an expense, and typing does not make them so."""
    documents = (
        await api_client.get(f"/api/v1/trips/{TRQ}/documents", headers=_as(CLAIMANT))
    ).json()
    promo = next(
        document for document in documents if document["source_filename"] == "14_promo_noise.eml"
    )

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents/{promo['external_id']}/correction",
        json=_correction(),
        headers=_as(CLAIMANT),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_claimable"
    assert promo["correctable"] is False


async def test_only_the_claimant_can_correct_their_own_evidence(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """404 rather than 403: a 403 confirms the trip exists, which is what a prober wants."""
    external_id, filename = await _unreadable_folio(api_client)

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents/{external_id}/correction",
        json=_correction(),
        headers=_as(OTHER_EMPLOYEE),
    )

    assert response.status_code == 404


async def test_a_line_whose_tax_exceeds_it_is_refused_at_the_boundary(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """The tax on a line is a component of its gross, not an addition to it."""
    external_id, filename = await _unreadable_folio(api_client)

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents/{external_id}/correction",
        json={
            "lines": [
                {
                    "description": "Scanned folio: room tariff",
                    "gross_amount": "5000.00",
                    "tax_amount": "6000.00",
                    "txn_date": "2026-06-16",
                }
            ]
        },
        headers=_as(CLAIMANT),
    )

    assert response.status_code == 422
    assert "cannot exceed the line itself" in response.text


# ----------------------------------------------------------------- the record


async def test_the_correction_is_on_the_audit_trail_with_its_figures(
    api_client: AsyncClient, db_session: AsyncSession, seeded_trip: TravelRequest
) -> None:
    """The rows are replaced by a later correction; the event is what survives it."""
    external_id, filename = await _unreadable_folio(api_client)
    await api_client.post(
        f"/api/v1/trips/{TRQ}/documents/{external_id}/correction",
        json=_correction(),
        headers=_as(CLAIMANT),
    )

    events = (
        (
            await db_session.execute(
                select(ClaimEvent).where(ClaimEvent.action == "document_corrected")
            )
        )
        .scalars()
        .all()
    )

    assert len(events) == 1
    assert events[0].payload["source_filename"] == filename
    assert events[0].payload["lines"][0]["gross_amount"] == "15000.00"
    assert events[0].payload["lines"][0]["nights"] == 3


async def test_a_corrected_document_says_so_on_the_document_list(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """The claimant needs to see that it took, and can still fix a figure they mistyped."""
    external_id, filename = await _unreadable_folio(api_client)
    await api_client.post(
        f"/api/v1/trips/{TRQ}/documents/{external_id}/correction",
        json=_correction(),
        headers=_as(CLAIMANT),
    )

    documents = (
        await api_client.get(f"/api/v1/trips/{TRQ}/documents", headers=_as(CLAIMANT))
    ).json()
    folio = next(document for document in documents if document["external_id"] == external_id)

    assert folio["extraction_status"] == "extracted"
    assert folio["manually_entered"] is True
    assert folio["correctable"] is True
    assert folio["needs_input_reason"] is None
