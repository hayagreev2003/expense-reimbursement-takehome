"""Unit 2: schema guarantees that the database enforces, not the application."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.db.models import (
    CityClass,
    ClaimEvent,
    Employee,
    Role,
    SettlementClaim,
)
from tests.db_helpers import (
    make_employee,
    make_policy_version,
    make_travel_request,
)

pytestmark = [pytest.mark.db, pytest.mark.asyncio]


async def test_money_round_trips_as_exact_decimal(db_session: AsyncSession) -> None:
    """The reason Money exists: no float in the money path.

    27318.04 is the sample trip's employee-paid gross. Through a float it comes back as
    27318.039999999997 and the claim stops reconciling against its own source bills.
    """
    employee = await make_employee(db_session)
    request = await make_travel_request(
        db_session, employee=employee, advance_requested=Decimal("27318.04")
    )
    db_session.expunge_all()

    reloaded = (
        await db_session.execute(select(type(request)).where(type(request).id == request.id))
    ).scalar_one()

    assert reloaded.advance_requested == Decimal("27318.04")
    assert isinstance(reloaded.advance_requested, Decimal)


async def test_money_is_stored_as_integer_paise(db_session: AsyncSession) -> None:
    employee = await make_employee(db_session)
    request = await make_travel_request(
        db_session, employee=employee, advance_requested=Decimal("20000.00")
    )

    raw = (
        await db_session.execute(
            text("SELECT advance_requested FROM travel_request WHERE id = :id"),
            {"id": request.id},
        )
    ).scalar_one()

    assert raw == 2_000_000


async def test_money_rejects_sub_paise_precision(db_session: AsyncSession) -> None:
    """Round-tripping silently would hide a division that was never quantised."""
    employee = await make_employee(db_session)

    # SQLAlchemy wraps a bind-processing error in StatementError, but the message and the
    # original exception both survive - assert on the cause so the test pins the real guard.
    with pytest.raises(StatementError) as exc_info:
        await make_travel_request(
            db_session, employee=employee, advance_requested=Decimal("100.005")
        )

    assert isinstance(exc_info.value.orig, ValueError)
    assert "sub-paise" in str(exc_info.value.orig)


async def test_enum_columns_persist_policy_wording(db_session: AsyncSession) -> None:
    """Roles must read as the policy document writes them, not as Python member names.

    The approval matrix in policy/versions/*.yaml says "Reporting Manager". If the column held
    "REPORTING_MANAGER", matrix lookups would need a translation table that would eventually
    drift.
    """
    await make_employee(db_session, emp_code="NX-9100", role=Role.REPORTING_MANAGER)

    stored = (
        await db_session.execute(text("SELECT role FROM employee WHERE emp_code = 'NX-9100'"))
    ).scalar_one()

    assert stored == "Reporting Manager"


async def test_invalid_enum_value_is_rejected_by_the_database(db_session: AsyncSession) -> None:
    """native_enum=False renders a CHECK constraint, so bad data cannot get in via raw SQL."""
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO employee "
                "(emp_code, name, email, designation, department, cost_centre, city, role) "
                "VALUES ('NX-BAD', 'X', 'x@y.z', 'D', 'Dept', 'CE1', 'Pune', 'Overlord')"
            )
        )


async def test_foreign_keys_are_enforced(db_session: AsyncSession) -> None:
    """SQLite ignores foreign keys unless the pragma is set per connection.

    Without the pragma every FK in models.py is decoration, and the tests that assume
    referential integrity would pass while proving nothing.
    """
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO advance (travel_request_id, reference, amount, disbursed_on, "
                "external_id) VALUES (999999, 'ADV/NOPE', 100, '2026-06-10', 'x-1')"
            )
        )


async def test_reporting_chain_walks_to_the_top(db_session: AsyncSession) -> None:
    await make_employee(db_session, emp_code="NX-T000", role=Role.MD)
    await make_employee(
        db_session,
        emp_code="NX-T100",
        role=Role.HEAD_OF_DEPARTMENT,
        reporting_manager_code="NX-T000",
    )
    await make_employee(
        db_session,
        emp_code="NX-T200",
        role=Role.EMPLOYEE,
        reporting_manager_code="NX-T100",
    )

    chain: list[str] = []
    code: str | None = "NX-T200"
    while code is not None:
        employee = (
            await db_session.execute(select(Employee).where(Employee.emp_code == code))
        ).scalar_one()
        chain.append(employee.emp_code)
        code = employee.reporting_manager_code

    assert chain == ["NX-T200", "NX-T100", "NX-T000"]


async def test_travel_request_rejects_reversed_dates(db_session: AsyncSession) -> None:
    employee = await make_employee(db_session)

    with pytest.raises(IntegrityError):
        await make_travel_request(
            db_session,
            employee=employee,
            from_date=date(2026, 6, 20),
            to_date=date(2026, 6, 16),
        )


async def test_payable_and_recoverable_are_mutually_exclusive(db_session: AsyncSession) -> None:
    """Template legend line 67. Both non-zero is arithmetically impossible, so forbid it."""
    employee = await make_employee(db_session)
    request = await make_travel_request(db_session, employee=employee)
    version = await make_policy_version(db_session)

    claim = SettlementClaim(
        travel_request_id=request.id,
        policy_version_id=version.id,
        payable=Decimal("6388.44"),
        recoverable=Decimal("100.00"),
    )
    db_session.add(claim)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_external_id_is_generated_and_unique(db_session: AsyncSession) -> None:
    """Clients address rows by this, so integer PKs never leak and cannot be enumerated."""
    employee = await make_employee(db_session)
    first = await make_travel_request(db_session, employee=employee, trq_id="TRQ-2026-9001")
    second = await make_travel_request(db_session, employee=employee, trq_id="TRQ-2026-9002")

    assert first.external_id and second.external_id
    assert first.external_id != second.external_id
    assert len(first.external_id) == 36


async def test_claim_event_cannot_be_updated(db_session: AsyncSession) -> None:
    """An audit trail application code can rewrite is not an audit trail."""
    event = ClaimEvent(action="ingested", payload={"file": "01_travel_approval_request.eml"})
    db_session.add(event)
    await db_session.flush()

    with pytest.raises(IntegrityError, match="append-only"):
        await db_session.execute(
            text("UPDATE claim_event SET action = 'tampered' WHERE id = :id"), {"id": event.id}
        )


async def test_claim_event_cannot_be_deleted(db_session: AsyncSession) -> None:
    event = ClaimEvent(action="duplicate_suppressed", payload={"fingerprint": "uber|172.00"})
    db_session.add(event)
    await db_session.flush()

    with pytest.raises(IntegrityError, match="append-only"):
        await db_session.execute(text("DELETE FROM claim_event WHERE id = :id"), {"id": event.id})


async def test_city_class_values_match_the_policy_document(db_session: AsyncSession) -> None:
    employee = await make_employee(db_session)
    request = await make_travel_request(db_session, employee=employee, city_class=CityClass.TIER_1)

    stored = (
        await db_session.execute(
            text("SELECT city_class FROM travel_request WHERE id = :id"), {"id": request.id}
        )
    ).scalar_one()

    assert stored == "Tier 1"
