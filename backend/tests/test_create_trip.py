"""Applying for a trip over HTTP.

Until this endpoint existed a trip could only come into being through `make seed`, which made
the product unusable by the person it is for: no trip, nothing to attach a bill to, nothing to
claim. These tests pin the three things that make the endpoint safe rather than merely present -
the identifier does not collide, the trip belongs to whoever applied, and a trip that ends
before it begins is refused at the boundary rather than stored.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.db.models import ClaimEvent, TravelRequest

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

CLAIMANT = "NX-4471"  # Chaitanya Reddy
OTHER_EMPLOYEE = "NX-4490"  # Imran Qureshi, uninvolved
MANAGER = "NX-2210"  # Suresh Iyer, Reporting Manager


def _as(emp_code: str) -> dict[str, str]:
    return {"X-Emp-Code": emp_code}


APPLICATION = {
    "destination_city": "Pune",
    "from_date": "2026-08-03",
    "to_date": "2026-08-06",
    "purpose": "Commissioning review at the Chakan line",
    "city_class": "Tier 2",
    "mode_of_travel": "Train",
    "visiting_company": "Harbin Forge Pvt Ltd",
}


async def test_applying_for_a_trip_returns_an_empty_draft_claim(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """The point of the endpoint: somewhere to attach the first bill."""
    created = await api_client.post("/api/v1/trips", json=APPLICATION, headers=_as(CLAIMANT))

    assert created.status_code == 201, created.text
    trip = created.json()
    assert trip["status"] == "draft"
    assert trip["payable"] == "0.00"
    assert trip["destination"] == "Pune"
    # §5.1: seven calendar days from the date of return.
    assert trip["submission_deadline"] == "2026-08-13"

    claim = await api_client.get(f"/api/v1/trips/{trip['trq_id']}/claim", headers=_as(CLAIMANT))
    assert claim.status_code == 200, claim.text
    assert claim.json()["lines"] == []
    # Nothing to submit yet, and the reason says so rather than the button simply not working.
    assert claim.json()["can_submit"] is False
    assert claim.json()["blocking_reasons"] == ["This claim has no reimbursable lines to submit."]


async def test_the_new_trq_id_does_not_collide_with_one_already_taken(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """The pack's trip is TRQ-2026-0001, so the next application is 0002, not a second 0001."""
    first = await api_client.post("/api/v1/trips", json=APPLICATION, headers=_as(CLAIMANT))
    second = await api_client.post("/api/v1/trips", json=APPLICATION, headers=_as(CLAIMANT))

    assert first.json()["trq_id"] == "TRQ-2026-0002"
    assert second.json()["trq_id"] == "TRQ-2026-0003"


async def test_the_trip_belongs_to_whoever_applied(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """Scoping is the same as for a seeded trip: an application is not public."""
    created = await api_client.post("/api/v1/trips", json=APPLICATION, headers=_as(CLAIMANT))
    trq_id = created.json()["trq_id"]

    mine = await api_client.get("/api/v1/trips", headers=_as(CLAIMANT))
    assert trq_id in [trip["trq_id"] for trip in mine.json()]

    theirs = await api_client.get(f"/api/v1/trips/{trq_id}/claim", headers=_as(OTHER_EMPLOYEE))
    assert theirs.status_code == 404

    # An approver is not an owner. The trip reaches them when it is routed, not before.
    queue = await api_client.get("/api/v1/trips", headers=_as(MANAGER))
    assert trq_id not in [trip["trq_id"] for trip in queue.json()]


async def test_an_approver_may_apply_for_their_own_trip(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """A manager travels too. The admin profile is about other people's claims, not their own."""
    created = await api_client.post("/api/v1/trips", json=APPLICATION, headers=_as(MANAGER))

    assert created.status_code == 201, created.text
    assert created.json()["employee_code"] == MANAGER


async def test_a_trip_that_ends_before_it_begins_is_refused(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """Refused at the boundary. The database has the same constraint; this is the better error."""
    response = await api_client.post(
        "/api/v1/trips",
        json={**APPLICATION, "from_date": "2026-08-06", "to_date": "2026-08-03"},
        headers=_as(CLAIMANT),
    )

    assert response.status_code == 422
    assert "cannot end before it begins" in response.text


async def test_an_unknown_city_class_is_refused_rather_than_stored(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    """City class decides which §3.1 limit applies, so a value policy cannot read is no value."""
    response = await api_client.post(
        "/api/v1/trips",
        json={**APPLICATION, "city_class": "Tier 9"},
        headers=_as(CLAIMANT),
    )

    assert response.status_code == 422


async def test_an_unidentified_caller_cannot_apply(
    api_client: AsyncClient, seeded_trip: TravelRequest
) -> None:
    response = await api_client.post("/api/v1/trips", json=APPLICATION)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_signed_in"


async def test_the_application_is_recorded_on_the_audit_trail(
    api_client: AsyncClient, db_session: AsyncSession, seeded_trip: TravelRequest
) -> None:
    """A trip appearing out of nowhere is exactly the thing an audit trail is for."""
    created = await api_client.post("/api/v1/trips", json=APPLICATION, headers=_as(CLAIMANT))
    trq_id = created.json()["trq_id"]

    stored = (
        await db_session.execute(select(TravelRequest).where(TravelRequest.trq_id == trq_id))
    ).scalar_one()
    events = (
        (
            await db_session.execute(
                select(ClaimEvent).where(ClaimEvent.travel_request_id == stored.id)
            )
        )
        .scalars()
        .all()
    )

    assert [event.action for event in events] == ["trip_created"]
    assert events[0].payload["trq_id"] == trq_id
    # Defaulted rather than asked for: the seeded trip's form words it this way.
    assert stored.travel_category == "Domestic - Tier 2"
    assert stored.cost_centre  # inherited from the employee master, not typed by the applicant
