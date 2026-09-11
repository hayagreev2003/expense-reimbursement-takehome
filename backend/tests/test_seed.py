"""Unit 2: seeding from the specification pack.

These run against the real pack/ files, not fixtures. If the pack changes shape, these fail -
which is the point: the pack is the specification.
"""

from datetime import date
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.config.settings import settings
from expense_api.db.models import Employee, PolicyVersion, Role
from expense_api.seed.employees import seed_employees
from expense_api.seed.policy import VERSIONS_DIR, seed_policy_versions

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

EMPLOYEE_CSV = settings.pack_dir / "employee_master.csv"


async def _count(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_seeds_every_employee_in_the_pack(db_session: AsyncSession) -> None:
    seeded = await seed_employees(db_session, EMPLOYEE_CSV)

    assert seeded == 9
    assert await _count(db_session, Employee) == 9


async def test_seeding_twice_does_not_duplicate(db_session: AsyncSession) -> None:
    """The container entrypoint seeds on every start, so this has to be safe."""
    await seed_employees(db_session, EMPLOYEE_CSV)
    await seed_employees(db_session, EMPLOYEE_CSV)

    assert await _count(db_session, Employee) == 9


async def test_reporting_chain_reaches_every_approval_level(db_session: AsyncSession) -> None:
    """The §2 matrix needs all four business levels reachable from the sample claimant.

    If any link is missing, routing silently stops short and a claim reaches Finance without
    the approvals its value requires.
    """
    await seed_employees(db_session, EMPLOYEE_CSV)

    chain: list[tuple[str, Role]] = []
    code: str | None = "NX-4471"
    while code is not None:
        employee = (
            await db_session.execute(select(Employee).where(Employee.emp_code == code))
        ).scalar_one()
        chain.append((employee.emp_code, employee.role))
        code = employee.reporting_manager_code

    assert chain == [
        ("NX-4471", Role.EMPLOYEE),
        ("NX-2210", Role.REPORTING_MANAGER),
        ("NX-1108", Role.HEAD_OF_DEPARTMENT),
        ("NX-1002", Role.HEAD_OF_DIVISION),
        ("NX-1000", Role.MD),
    ]


async def test_the_md_has_no_manager(db_session: AsyncSession) -> None:
    """This is what terminates the chain walk, so it is load-bearing, not incidental."""
    await seed_employees(db_session, EMPLOYEE_CSV)

    md = (
        await db_session.execute(select(Employee).where(Employee.emp_code == "NX-1000"))
    ).scalar_one()

    assert md.role is Role.MD
    assert md.reporting_manager_code is None


async def test_finance_staff_are_seeded(db_session: AsyncSession) -> None:
    """§2.1 requires Finance verification on every claim, so a Finance actor must exist."""
    await seed_employees(db_session, EMPLOYEE_CSV)

    finance = (
        (await db_session.execute(select(Employee).where(Employee.role == Role.FINANCE)))
        .scalars()
        .all()
    )

    assert {e.emp_code for e in finance} == {"NX-3305", "NX-3300"}


async def test_missing_employee_csv_fails_loudly(db_session: AsyncSession) -> None:
    with pytest.raises(FileNotFoundError):
        await seed_employees(db_session, Path("/nonexistent/employee_master.csv"))


async def test_seeds_the_policy_version(db_session: AsyncSession) -> None:
    count = await seed_policy_versions(db_session)

    assert count == 1
    version = (await db_session.execute(select(PolicyVersion))).scalar_one()
    assert version.document_id == "NTX-HR-POL-11"
    assert version.revision == "Rev 4"
    assert version.effective_from == date(2026, 4, 1)
    assert version.effective_to is None


async def test_policy_version_is_in_force_for_the_sample_trip(db_session: AsyncSession) -> None:
    """A claim is evaluated against the version in force for its travel dates."""
    await seed_policy_versions(db_session)
    trip_start, trip_end = date(2026, 6, 16), date(2026, 6, 20)

    version = (
        await db_session.execute(
            select(PolicyVersion).where(PolicyVersion.effective_from <= trip_start)
        )
    ).scalar_one()

    assert version.effective_to is None or version.effective_to >= trip_end


async def test_seeding_policy_twice_does_not_duplicate(db_session: AsyncSession) -> None:
    await seed_policy_versions(db_session)
    await seed_policy_versions(db_session)

    assert await _count(db_session, PolicyVersion) == 1


async def test_policy_payload_carries_the_limits_evaluation_needs(
    db_session: AsyncSession,
) -> None:
    await seed_policy_versions(db_session)
    payload = (await db_session.execute(select(PolicyVersion))).scalar_one().payload

    assert payload["lodging"]["limits_per_night"]["Tier 1"] == 6000
    assert payload["meals"]["daily_limits"]["Tier 1"] == 1500
    assert payload["meals"]["bill_required_above"] == 500
    assert payload["business_entertainment"]["prior_approval_threshold"] == 2000
    assert payload["submission"]["deadline_days_after_return"] == 7
    assert payload["submission"]["payment_run_days"] == [10, 25]
    assert payload["advance"]["max_fraction_of_employee_borne_estimate"] == 0.60


async def test_approval_matrix_bands_match_the_policy(db_session: AsyncSession) -> None:
    await seed_policy_versions(db_session)
    matrix = (
        (await db_session.execute(select(PolicyVersion))).scalar_one().payload["approval_matrix"]
    )

    assert matrix[0] == {"min": 0, "max": 25000, "roles": ["Reporting Manager"]}
    assert matrix[1]["roles"] == ["Reporting Manager", "Head of Department"]
    assert matrix[-1]["max"] is None

    # Roles in the matrix must be values the Role enum actually has, or routing cannot resolve
    # an approver for a band.
    for band in matrix:
        for role in band["roles"]:
            assert role in {member.value for member in Role}


async def test_tier_lists_record_whether_they_came_from_the_policy(
    db_session: AsyncSession,
) -> None:
    """The policy enumerates Tier 1 only. The Tier 2 list is ours and must say so.

    If this marker is ever dropped, an assumption starts reading as policy - and someone
    eventually cites it back to Finance as though the document said it.
    """
    await seed_policy_versions(db_session)
    city_classes = (
        (await db_session.execute(select(PolicyVersion))).scalar_one().payload["city_classes"]
    )

    assert city_classes["tier_1_cities"]["source"] == "policy"
    assert city_classes["tier_2_cities"]["source"] == "assumption"
    assert city_classes["default_class"] == "Tier 3"
    assert "Bengaluru" in city_classes["tier_1_cities"]["cities"]


async def test_non_reimbursable_list_does_not_include_food(db_session: AsyncSession) -> None:
    """§4 omits food deliberately.

    In-room dining on a hotel folio is a meal subject to the daily cap, not an excluded folio
    extra. Adding "dining" or "food" here would make the sample claim understate by 1,120.
    """
    await seed_policy_versions(db_session)
    categories = (
        (await db_session.execute(select(PolicyVersion)))
        .scalar_one()
        .payload["non_reimbursable"]["categories"]
    )

    assert "laundry" in categories
    assert "mini bar" in categories
    for forbidden in ("food", "dining", "in-room dining", "meals"):
        assert forbidden not in categories


async def test_policy_file_missing_a_required_key_fails_loudly(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """A version without its approval matrix would produce claims that route to nobody."""
    source = yaml.safe_load((VERSIONS_DIR / "ntx-hr-pol-11-rev4.yaml").read_text())
    del source["approval_matrix"]
    (tmp_path / "broken.yaml").write_text(yaml.safe_dump(source))

    with pytest.raises(ValueError, match="approval_matrix"):
        await seed_policy_versions(db_session, tmp_path)


async def test_empty_versions_directory_fails_loudly(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError):
        await seed_policy_versions(db_session, tmp_path)
