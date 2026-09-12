"""The two-profile workflow, over HTTP: upload, submit, notify, decide, notify.

This is the second acceptance test. The first one (test_acceptance_nortex_trip.py) proves the
figures; this one proves the hand-offs - that a claim reaches exactly one approver at a time,
that both sides are told when it moves, and that nobody can act out of turn or on a stale view.

It runs against the real pack and the real routers, with only the database session swapped for
a transaction that is rolled back.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.config.settings import settings
from expense_api.db.models import TravelRequest
from expense_api.evidence.extractors.ocr import ocr_available

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

pytest.importorskip("pytesseract")
if not ocr_available():  # pragma: no cover - depends on the host
    pytest.skip("tesseract is required for the dinner bill", allow_module_level=True)

TRQ = "TRQ-2026-0001"
CLAIMANT = "NX-4471"  # Chaitanya Reddy, the traveller
MANAGER = "NX-2210"  # Suresh Iyer, Reporting Manager
HOD = "NX-1108"  # Meera Krishnan, Head of Department
FINANCE = "NX-3300"  # Kavitha Balan, Controller
OTHER_EMPLOYEE = "NX-4490"  # Imran Qureshi, uninvolved


def _as(emp_code: str) -> dict[str, str]:
    return {"X-Emp-Code": emp_code}


async def _submit_ready_claim(client: AsyncClient) -> None:
    """Withdraw the one held line, then submit.

    The dinner is held because §3.5 needs attendee names, and a held line blocks submission by
    design. Withdrawing it is the employee's documented escape, and it is what makes this trip
    submittable at all.
    """
    withdrawn = await client.post(
        f"/api/v1/trips/{TRQ}/claim/withdraw",
        json={"description": "Dinner, 4 covers", "reason": "Filed separately."},
        headers=_as(CLAIMANT),
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["can_submit"] is True

    submitted = await client.post(f"/api/v1/trips/{TRQ}/claim/submit", headers=_as(CLAIMANT))
    assert submitted.status_code == 200, submitted.text


# ------------------------------------------------------------------ identity


async def test_an_unidentified_caller_gets_401_not_an_empty_list(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """No header, no data. An empty 200 would read as "you have no trips"."""
    response = await api_client.get("/api/v1/trips")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_signed_in"


async def test_profiles_are_derived_from_the_employee_master(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    employee = await api_client.get("/api/v1/me", headers=_as(CLAIMANT))
    approver = await api_client.get("/api/v1/me", headers=_as(MANAGER))
    finance = await api_client.get("/api/v1/me", headers=_as(FINANCE))

    assert employee.json()["profile"] == "employee"
    assert approver.json()["profile"] == "admin"
    # Finance is not an approver in the reporting line, but it acts on other people's claims.
    assert finance.json()["profile"] == "admin"


async def test_an_employee_sees_only_their_own_trips(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    mine = await api_client.get("/api/v1/trips", headers=_as(CLAIMANT))
    theirs = await api_client.get("/api/v1/trips", headers=_as(OTHER_EMPLOYEE))

    assert [trip["trq_id"] for trip in mine.json()] == [TRQ]
    assert theirs.json() == []


async def test_another_employees_claim_is_404_not_403(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """A 403 would confirm the claim exists, which is what a prober is after."""
    response = await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(OTHER_EMPLOYEE))

    assert response.status_code == 404


async def test_an_approver_cannot_see_a_draft_before_it_is_submitted(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """A draft belongs to its author. Routing is what makes it visible."""
    trips = await api_client.get("/api/v1/trips", headers=_as(MANAGER))
    claim = await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(MANAGER))

    assert trips.json() == []
    assert claim.status_code == 404


# -------------------------------------------------------------------- upload


async def test_a_photographed_bill_becomes_evidence(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    image = (settings.pack_dir / "receipts" / "dinner_bill_18jun.png").read_bytes()

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents",
        files={"file": ("late_dinner.png", image, "image/png")},
        data={"doc_kind": "restaurant_bill", "note": "Bill the travel desk never copied me on."},
        headers=_as(CLAIMANT),
    )

    assert response.status_code == 201, response.text
    document = response.json()["document"]
    assert document["doc_kind"] == "restaurant_bill"
    assert document["uploaded"] is True
    # The proof reference names the image, not "attached mail" - the form's legend requires it.
    assert "late_dinner.png" in document["proof_ref"]

    listed = await api_client.get(f"/api/v1/trips/{TRQ}/documents", headers=_as(CLAIMANT))
    assert any(row["source_filename"] == "late_dinner.eml" for row in listed.json())


async def test_an_upload_never_lands_inside_the_read_only_pack(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    image = (settings.pack_dir / "receipts" / "dinner_bill_18jun.png").read_bytes()

    await api_client.post(
        f"/api/v1/trips/{TRQ}/documents",
        files={"file": ("../../escape.png", image, "image/png")},
        data={"doc_kind": "restaurant_bill"},
        headers=_as(CLAIMANT),
    )

    written = list(Path(settings.upload_dir).rglob("*.png"))
    assert written, "the upload should have been stored somewhere"
    for path in written:
        assert path.resolve().is_relative_to(settings.upload_dir.resolve())
    assert not (settings.pack_dir / "escape.png").exists()


async def test_an_image_without_a_declared_kind_is_refused(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """A photograph has no sender and no subject, so guessing its kind silently picks the wrong
    parser and produces amounts that look plausible and are wrong."""
    image = (settings.pack_dir / "receipts" / "dinner_bill_18jun.png").read_bytes()

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents",
        files={"file": ("mystery.png", image, "image/png")},
        headers=_as(CLAIMANT),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "upload_rejected"


async def test_an_unreadable_file_type_is_refused(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents",
        files={"file": ("notes.txt", b"dinner was 4200", "text/plain")},
        data={"doc_kind": "restaurant_bill"},
        headers=_as(CLAIMANT),
    )

    assert response.status_code == 422


async def test_only_the_claimant_can_upload_to_a_claim(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    image = (settings.pack_dir / "receipts" / "dinner_bill_18jun.png").read_bytes()

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents",
        files={"file": ("someone_elses.png", image, "image/png")},
        data={"doc_kind": "restaurant_bill"},
        headers=_as(OTHER_EMPLOYEE),
    )

    assert response.status_code == 404


async def test_mailed_evidence_cannot_be_deleted_by_the_claimant(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """An inbox is a record of what arrived. Deleting an inconvenient receipt is exactly the
    failure this system exists to prevent."""
    documents = (
        await api_client.get(f"/api/v1/trips/{TRQ}/documents", headers=_as(CLAIMANT))
    ).json()
    mailed = next(row for row in documents if not row["uploaded"])

    response = await api_client.delete(
        f"/api/v1/trips/{TRQ}/documents/{mailed['external_id']}", headers=_as(CLAIMANT)
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_removable"


# -------------------------------------------------------------------- submit


async def test_a_held_line_blocks_submission(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    response = await api_client.post(f"/api/v1/trips/{TRQ}/claim/submit", headers=_as(CLAIMANT))

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "claim_incomplete"
    assert "Dinner" in response.json()["detail"]["message"]


async def test_submission_routes_the_claim_and_notifies_both_sides(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    await _submit_ready_claim(api_client)

    claim = (await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(CLAIMANT))).json()
    assert claim["status"] == "pending_approval"
    # Frozen: what the approver sees cannot move underneath them.
    assert claim["frozen"] is True
    assert claim["version"] >= 2

    # Withdrawing the dinner drops the claim under 25,000, so §2 needs only the manager.
    roles = [step["role"] for step in claim["chain"]]
    assert roles == ["Reporting Manager", "Finance"]

    employee_inbox = (await api_client.get("/api/v1/notifications", headers=_as(CLAIMANT))).json()
    assert employee_inbox["unread_count"] == 1
    assert employee_inbox["items"][0]["kind"] == "claim_submitted"

    manager_inbox = (await api_client.get("/api/v1/notifications", headers=_as(MANAGER))).json()
    assert manager_inbox["unread_count"] == 1
    assert manager_inbox["items"][0]["kind"] == "awaiting_your_approval"
    assert TRQ in manager_inbox["items"][0]["title"]


async def test_a_submitted_claim_is_locked_against_further_uploads(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """Evidence arriving after an approver has seen the claim would change what they approved."""
    await _submit_ready_claim(api_client)
    image = (settings.pack_dir / "receipts" / "dinner_bill_18jun.png").read_bytes()

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents",
        files={"file": ("afterthought.png", image, "image/png")},
        data={"doc_kind": "restaurant_bill"},
        headers=_as(CLAIMANT),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "claim_locked"


# ------------------------------------------------------------------ approval


async def test_the_claim_lands_in_exactly_one_queue(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    await _submit_ready_claim(api_client)

    manager_queue = (await api_client.get("/api/v1/approvals", headers=_as(MANAGER))).json()
    finance_queue = (await api_client.get("/api/v1/approvals", headers=_as(FINANCE))).json()

    assert [item["trq_id"] for item in manager_queue] == [TRQ]
    assert manager_queue[0]["role"] == "Reporting Manager"
    # Finance is on the chain but not yet at the front of it.
    assert finance_queue == []


async def test_an_employee_cannot_reach_the_approval_queue(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    response = await api_client.get("/api/v1/approvals", headers=_as(CLAIMANT))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "not_an_approver"


async def test_an_approver_out_of_turn_is_refused(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    await _submit_ready_claim(api_client)
    claim = (await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(CLAIMANT))).json()

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/claim/decision",
        json={
            "decision": "approved",
            "approver_code": FINANCE,
            "expected_version": claim["version"],
        },
        headers=_as(FINANCE),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "not_your_step"


async def test_nobody_can_decide_on_someone_elses_behalf(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    await _submit_ready_claim(api_client)
    claim = (await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(CLAIMANT))).json()

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/claim/decision",
        json={
            "decision": "approved",
            "approver_code": MANAGER,
            "expected_version": claim["version"],
        },
        headers=_as(HOD),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "approver_mismatch"


async def test_a_stale_view_cannot_decide(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """Two approvers who both loaded the claim: the second one is told to look again."""
    await _submit_ready_claim(api_client)

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/claim/decision",
        json={"decision": "approved", "approver_code": MANAGER, "expected_version": 1},
        headers=_as(MANAGER),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_claim"


async def test_approval_moves_the_claim_on_and_tells_everyone(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    await _submit_ready_claim(api_client)
    await api_client.post("/api/v1/notifications/read-all", headers=_as(CLAIMANT))
    claim = (await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(MANAGER))).json()

    decided = await api_client.post(
        f"/api/v1/trips/{TRQ}/claim/decision",
        json={
            "decision": "approved",
            "approver_code": MANAGER,
            "expected_version": claim["version"],
            "remarks": "Checked against the travel request.",
        },
        headers=_as(MANAGER),
    )

    assert decided.status_code == 200, decided.text
    assert decided.json()["claim_status"] == "pending_finance"

    employee_inbox = (await api_client.get("/api/v1/notifications", headers=_as(CLAIMANT))).json()
    assert employee_inbox["unread_count"] == 1
    assert employee_inbox["items"][0]["kind"] == "claim_approved"
    assert "Suresh Iyer" in employee_inbox["items"][0]["title"]

    finance_queue = (await api_client.get("/api/v1/approvals", headers=_as(FINANCE))).json()
    assert [item["trq_id"] for item in finance_queue] == [TRQ]
    manager_queue = (await api_client.get("/api/v1/approvals", headers=_as(MANAGER))).json()
    assert manager_queue == []


async def test_finance_verification_is_the_last_step(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    await _submit_ready_claim(api_client)

    for approver in (MANAGER, FINANCE):
        claim = (await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(approver))).json()
        decided = await api_client.post(
            f"/api/v1/trips/{TRQ}/claim/decision",
            json={
                "decision": "approved",
                "approver_code": approver,
                "expected_version": claim["version"],
            },
            headers=_as(approver),
        )
        assert decided.status_code == 200, decided.text

    assert decided.json()["claim_status"] == "verified"
    employee_inbox = (await api_client.get("/api/v1/notifications", headers=_as(CLAIMANT))).json()
    assert employee_inbox["items"][0]["kind"] == "claim_verified"


# -------------------------------------------------------------------- return


async def test_a_return_needs_remarks(api_client: AsyncClient, seeded_trip: TravelRequest) -> None:
    """§2.3 sends it back for correction. Without remarks the employee is told only that it
    came back, which is the follow-up loop this system exists to close."""
    await _submit_ready_claim(api_client)
    claim = (await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(MANAGER))).json()

    response = await api_client.post(
        f"/api/v1/trips/{TRQ}/claim/decision",
        json={
            "decision": "returned",
            "approver_code": MANAGER,
            "expected_version": claim["version"],
            "remarks": "   ",
        },
        headers=_as(MANAGER),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "remarks_required"


async def test_a_returned_claim_goes_back_to_draft_and_can_be_resubmitted(
    api_client: AsyncClient, seeded_trip: TravelRequest, db_session: AsyncSession
) -> None:
    await _submit_ready_claim(api_client)
    claim = (await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(MANAGER))).json()

    returned = await api_client.post(
        f"/api/v1/trips/{TRQ}/claim/decision",
        json={
            "decision": "returned",
            "approver_code": MANAGER,
            "expected_version": claim["version"],
            "remarks": "Attach the hotel folio page that shows the room rate.",
        },
        headers=_as(MANAGER),
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["claim_status"] == "draft"

    employee_inbox = (await api_client.get("/api/v1/notifications", headers=_as(CLAIMANT))).json()
    assert employee_inbox["items"][0]["kind"] == "claim_returned"
    assert "hotel folio" in employee_inbox["items"][0]["body"]

    # Back in the employee's hands: editable again, and against the same Travel Request ID.
    image = (settings.pack_dir / "receipts" / "hotel_invoice_1188.png").read_bytes()
    upload = await api_client.post(
        f"/api/v1/trips/{TRQ}/documents",
        files={"file": ("folio_page.png", image, "image/png")},
        data={"doc_kind": "hotel_invoice"},
        headers=_as(CLAIMANT),
    )
    assert upload.status_code == 201, upload.text

    resubmitted = await api_client.post(f"/api/v1/trips/{TRQ}/claim/submit", headers=_as(CLAIMANT))
    assert resubmitted.status_code in (200, 422)


async def test_a_return_does_not_erase_what_an_approver_already_decided(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """The manager approved it; Finance sent it back. His own record has to survive that.

    A return supersedes the round it ends, so a queue scoped to the current round would show
    the approver an empty history for a claim they signed off on an hour earlier.
    """
    await _submit_ready_claim(api_client)

    claim = (await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(MANAGER))).json()
    await api_client.post(
        f"/api/v1/trips/{TRQ}/claim/decision",
        json={
            "decision": "approved",
            "approver_code": MANAGER,
            "expected_version": claim["version"],
        },
        headers=_as(MANAGER),
    )

    claim = (await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers=_as(FINANCE))).json()
    returned = await api_client.post(
        f"/api/v1/trips/{TRQ}/claim/decision",
        json={
            "decision": "returned",
            "approver_code": FINANCE,
            "expected_version": claim["version"],
            "remarks": "Folio page missing.",
        },
        headers=_as(FINANCE),
    )
    assert returned.json()["claim_status"] == "draft"

    decided = (await api_client.get("/api/v1/approvals?scope=acted", headers=_as(MANAGER))).json()
    assert [item["trq_id"] for item in decided] == [TRQ]
    assert decided[0]["decision"] == "approved"

    # And it is no longer waiting on him: the claim is back with the employee.
    pending = (await api_client.get("/api/v1/approvals?scope=pending", headers=_as(MANAGER))).json()
    assert pending == []


# ------------------------------------------------------------- notifications


async def test_marking_read_only_affects_the_recipient(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """Two rows, one event. The employee clearing theirs must not clear the approver's."""
    await _submit_ready_claim(api_client)

    cleared = await api_client.post("/api/v1/notifications/read-all", headers=_as(CLAIMANT))
    assert cleared.json()["unread_count"] == 0

    manager_inbox = (await api_client.get("/api/v1/notifications", headers=_as(MANAGER))).json()
    assert manager_inbox["unread_count"] == 1


async def test_someone_elses_notification_is_404(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    await _submit_ready_claim(api_client)
    manager_inbox = (await api_client.get("/api/v1/notifications", headers=_as(MANAGER))).json()
    external_id = manager_inbox["items"][0]["external_id"]

    response = await api_client.post(
        f"/api/v1/notifications/{external_id}/read", headers=_as(CLAIMANT)
    )

    assert response.status_code == 404
