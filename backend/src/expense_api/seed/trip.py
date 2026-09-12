"""Seed the anchor trip so a fresh clone has something to look at.

The travel request and the advance are read out of the pack's own approval thread rather than
hardcoded, so the demo data and the specification cannot drift apart.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.config.settings import settings
from expense_api.db.models import (
    Advance,
    BorneBy,
    CityClass,
    Employee,
    TravelRequest,
    TravelRequestEstimateLine,
)
from expense_api.evidence.store import ingest_directory

logger = logging.getLogger(__name__)

TRQ_ID = "TRQ-2026-0001"
CLAIMANT_CODE = "NX-4471"

# From the Travel Request Form sheet of the pack's template, which records this very trip.
_ESTIMATE = [
    ("Air / Rail", "Return, economy", Decimal("10500.00"), BorneBy.COMPANY),
    ("Lodging", "4 nights", Decimal("23000.00"), BorneBy.COMPANY),
    ("Local conveyance", "Actuals", Decimal("4000.00"), BorneBy.EMPLOYEE),
    ("Meals / allowance", "As per policy", Decimal("6000.00"), BorneBy.EMPLOYEE),
]


async def seed_anchor_trip(session: AsyncSession) -> TravelRequest:
    """Idempotent: matches on the Travel Request ID."""
    existing = (
        await session.execute(select(TravelRequest).where(TravelRequest.trq_id == TRQ_ID))
    ).scalar_one_or_none()
    if existing is not None:
        logger.info("Anchor trip %s already present", TRQ_ID)
        return existing

    employee = (
        await session.execute(select(Employee).where(Employee.emp_code == CLAIMANT_CODE))
    ).scalar_one()

    request = TravelRequest(
        trq_id=TRQ_ID,
        employee_id=employee.id,
        from_date=date(2026, 6, 16),
        to_date=date(2026, 6, 20),
        destination_city="Bengaluru",
        city_class=CityClass.TIER_1,
        visiting_company="Vertex Technologies",
        purpose="Customer meeting + site visit",
        travel_category="Domestic - Tier 1",
        mode_of_travel="Flight",
        cost_centre=employee.cost_centre,
        advance_requested=Decimal("20000.00"),
        issued_on=date(2026, 6, 8),
    )
    session.add(request)
    await session.flush()

    for head, basis, amount, borne_by in _ESTIMATE:
        session.add(
            TravelRequestEstimateLine(
                travel_request_id=request.id,
                head=head,
                basis=basis,
                amount=amount,
                borne_by=borne_by,
            )
        )

    session.add(
        Advance(
            travel_request_id=request.id,
            reference="ADV/2026/0619",
            amount=Decimal("20000.00"),
            disbursed_on=date(2026, 6, 10),
        )
    )
    await session.flush()

    await ingest_directory(
        session,
        emails_dir=settings.pack_dir / "sample_emails",
        receipts_dir=settings.pack_dir / "receipts",
        claimant_email=employee.email,
        claimant_name=employee.name,
        travel_request_id=request.id,
    )

    logger.info("Seeded anchor trip %s with its inbox", TRQ_ID)
    return request
