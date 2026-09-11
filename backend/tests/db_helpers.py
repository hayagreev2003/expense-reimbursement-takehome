"""Row builders for tests.

Plain async functions taking a session plus keyword-only arguments, rather than a factory
library. Each one inserts the minimum a valid row needs and flushes, so a test only states the
fields it actually cares about.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.db.models import (
    Advance,
    BorneBy,
    CityClass,
    Employee,
    PolicyVersion,
    Role,
    TravelRequest,
    TravelRequestEstimateLine,
)


async def make_employee(
    session: AsyncSession,
    *,
    emp_code: str = "NX-9001",
    name: str = "Test Employee",
    email: str | None = None,
    designation: str = "Manager",
    department: str = "Sales",
    cost_centre: str = "CE110",
    city: str = "Pune",
    role: Role = Role.EMPLOYEE,
    reporting_manager_code: str | None = None,
) -> Employee:
    employee = Employee(
        emp_code=emp_code,
        name=name,
        email=email or f"{emp_code.lower()}@nortexindustries.com",
        designation=designation,
        department=department,
        cost_centre=cost_centre,
        city=city,
        role=role,
        reporting_manager_code=reporting_manager_code,
    )
    session.add(employee)
    await session.flush()
    return employee


async def make_policy_version(
    session: AsyncSession,
    *,
    document_id: str = "NTX-HR-POL-11",
    revision: str = "Rev 4",
    effective_from: date = date(2026, 4, 1),
    effective_to: date | None = None,
    payload: dict | None = None,
) -> PolicyVersion:
    version = PolicyVersion(
        document_id=document_id,
        revision=revision,
        effective_from=effective_from,
        effective_to=effective_to,
        payload=payload if payload is not None else {"lodging": {"limits_per_night": {}}},
    )
    session.add(version)
    await session.flush()
    return version


async def make_travel_request(
    session: AsyncSession,
    *,
    employee: Employee,
    trq_id: str = "TRQ-2026-0001",
    from_date: date = date(2026, 6, 16),
    to_date: date = date(2026, 6, 20),
    destination_city: str = "Bengaluru",
    city_class: CityClass = CityClass.TIER_1,
    visiting_company: str | None = "Vertex Technologies",
    purpose: str = "Customer meeting + site visit",
    travel_category: str = "Domestic - Tier 1",
    mode_of_travel: str = "Flight",
    advance_requested: Decimal | None = Decimal("20000.00"),
) -> TravelRequest:
    request = TravelRequest(
        trq_id=trq_id,
        employee_id=employee.id,
        from_date=from_date,
        to_date=to_date,
        destination_city=destination_city,
        city_class=city_class,
        visiting_company=visiting_company,
        purpose=purpose,
        travel_category=travel_category,
        mode_of_travel=mode_of_travel,
        cost_centre=employee.cost_centre,
        advance_requested=advance_requested,
    )
    session.add(request)
    await session.flush()
    return request


async def make_estimate_line(
    session: AsyncSession,
    *,
    travel_request: TravelRequest,
    head: str = "Lodging",
    basis: str | None = "4 nights",
    amount: Decimal = Decimal("23000.00"),
    borne_by: BorneBy = BorneBy.COMPANY,
) -> TravelRequestEstimateLine:
    line = TravelRequestEstimateLine(
        travel_request_id=travel_request.id,
        head=head,
        basis=basis,
        amount=amount,
        borne_by=borne_by,
    )
    session.add(line)
    await session.flush()
    return line


async def make_advance(
    session: AsyncSession,
    *,
    travel_request: TravelRequest,
    reference: str = "ADV/2026/0619",
    amount: Decimal = Decimal("20000.00"),
    disbursed_on: date = date(2026, 6, 10),
) -> Advance:
    advance = Advance(
        travel_request_id=travel_request.id,
        reference=reference,
        amount=amount,
        disbursed_on=disbursed_on,
    )
    session.add(advance)
    await session.flush()
    return advance
