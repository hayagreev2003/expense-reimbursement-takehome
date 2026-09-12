"""The demo reset: a hosted walkthrough has no shell, so `make reset-db` is out of reach.

Two things have to hold. The gate has to be closed by default - the endpoint deletes every
claim in the database - and the reset has to leave the demo genuinely replayable, which means
the anchor trip and its inbox are back and nothing that was claimed against them survives.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.config.settings import settings
from expense_api.db.models import (
    ClaimEvent,
    EvidenceDocument,
    SettlementClaim,
    TravelRequest,
)

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

TRQ = "TRQ-2026-0001"
CLAIMANT = "NX-4471"


@pytest.fixture
def reset_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "demo_reset_enabled", True)
    monkeypatch.setattr(settings, "demo_reset_token", None)


async def _count(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


# ------------------------------------------------------------------ the gate


async def test_the_route_is_404_when_the_gate_is_closed(
    api_client: AsyncClient,
    seeded_trip: TravelRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """404, not 403. A 403 confirms that a wipe-everything endpoint is there to be found."""
    # Set explicitly rather than relied on: this is the one test whose subject is the gate being
    # closed, and it must not quietly pass because nobody happened to turn it on.
    monkeypatch.setattr(settings, "demo_reset_enabled", False)

    response = await api_client.post("/api/v1/demo/reset")

    assert response.status_code == 404


async def test_a_wrong_token_is_refused(
    api_client: AsyncClient,
    seeded_trip: TravelRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "demo_reset_enabled", True)
    monkeypatch.setattr(settings, "demo_reset_token", "correct-horse")

    missing = await api_client.post("/api/v1/demo/reset")
    wrong = await api_client.post("/api/v1/demo/reset", headers={"X-Demo-Token": "nope"})
    right = await api_client.post("/api/v1/demo/reset", headers={"X-Demo-Token": "correct-horse"})

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert wrong.json()["detail"]["code"] == "bad_demo_token"
    assert right.status_code == 200


async def test_it_needs_no_profile_header(
    api_client: AsyncClient, seeded_trip: TravelRequest, reset_enabled: None
) -> None:
    """The reset deletes claims for every profile, so there is no caller to scope it to."""
    response = await api_client.post("/api/v1/demo/reset")

    assert response.status_code == 200


# ----------------------------------------------------------------- the reset


async def test_it_puts_the_trip_and_its_inbox_back(
    api_client: AsyncClient,
    db_session: AsyncSession,
    seeded_trip: TravelRequest,
    reset_enabled: None,
) -> None:
    evidence_before = await _count(db_session, EvidenceDocument)
    assert evidence_before > 0

    body = (await api_client.post("/api/v1/demo/reset")).json()

    assert body["trq_id"] == TRQ
    assert body["employees"] == 9
    assert body["policy_versions"] >= 1
    assert await _count(db_session, TravelRequest) == 1
    assert await _count(db_session, EvidenceDocument) == evidence_before

    # And the trip is reachable over HTTP again, as a draft.
    claim = await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers={"X-Emp-Code": CLAIMANT})
    assert claim.status_code == 200
    assert claim.json()["status"] == "draft"


async def test_a_submitted_claim_does_not_survive(
    api_client: AsyncClient,
    db_session: AsyncSession,
    seeded_trip: TravelRequest,
    reset_enabled: None,
) -> None:
    """The whole point: show the flow, then show it again from the top."""
    withdrawn = await api_client.post(
        f"/api/v1/trips/{TRQ}/claim/withdraw",
        json={"description": "Dinner, 4 covers", "reason": "Filed separately."},
        headers={"X-Emp-Code": CLAIMANT},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    submitted = await api_client.post(
        f"/api/v1/trips/{TRQ}/claim/submit", headers={"X-Emp-Code": CLAIMANT}
    )
    assert submitted.status_code == 200, submitted.text
    assert await _count(db_session, SettlementClaim) == 1

    response = await api_client.post("/api/v1/demo/reset")

    assert response.status_code == 200
    assert response.json()["deleted_rows"] > 0
    assert await _count(db_session, SettlementClaim) == 0


async def test_a_withdrawn_line_is_held_again_afterwards(
    api_client: AsyncClient,
    seeded_trip: TravelRequest,
    reset_enabled: None,
) -> None:
    """Withdrawals are per-process state, not rows, so the wipe alone does not undo them.

    This is the failure the reset exists to prevent: the database goes back but the held line
    is still withdrawn, so the claim submits straight away and the step the walkthrough is
    meant to show never happens.
    """
    withdrawn = await api_client.post(
        f"/api/v1/trips/{TRQ}/claim/withdraw",
        json={"description": "Dinner, 4 covers", "reason": "Filed separately."},
        headers={"X-Emp-Code": CLAIMANT},
    )
    assert withdrawn.json()["can_submit"] is True

    await api_client.post("/api/v1/demo/reset")

    claim = (
        await api_client.get(f"/api/v1/trips/{TRQ}/claim", headers={"X-Emp-Code": CLAIMANT})
    ).json()

    assert claim["can_submit"] is False
    assert claim["blocking_reasons"], "the dinner should block submission again"
    statuses = {line["description"]: line["status"] for line in claim["lines"]}
    assert statuses["Dinner, 4 covers"] == "held"


async def test_the_audit_trail_is_append_only_again_afterwards(
    api_client: AsyncClient,
    db_session: AsyncSession,
    seeded_trip: TravelRequest,
    reset_enabled: None,
) -> None:
    """The reset has to drop the claim_event triggers to wipe it. They must come back.

    If they did not, every later write path would be able to rewrite the audit trail and
    nothing would say so.
    """
    await api_client.post("/api/v1/demo/reset")

    event = (await db_session.execute(select(ClaimEvent).limit(1))).scalars().first()
    assert event is not None, "the re-seeded inbox should have logged events"

    with pytest.raises(Exception, match="append-only"):
        await db_session.delete(event)
        await db_session.flush()
