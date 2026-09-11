"""Seed the employee master from the specification pack.

Idempotent: matches on emp_code and updates in place, so running it twice leaves nine
employees rather than eighteen.
"""

import csv
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.db.models import Employee, Role

logger = logging.getLogger(__name__)

# Columns the pack's CSV actually has. A missing one is a hard error rather than a None field -
# a half-seeded employee master produces an approval chain that ends nowhere.
_REQUIRED_COLUMNS = {
    "emp_code",
    "name",
    "email",
    "designation",
    "department",
    "cost_centre",
    "city",
    "reporting_manager_code",
    "role",
}


async def seed_employees(session: AsyncSession, csv_path: Path) -> int:
    if not csv_path.exists():
        raise FileNotFoundError(f"Employee master not found at {csv_path}")

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise ValueError(f"Employee master at {csv_path} is empty")

    missing = _REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        raise ValueError(f"Employee master is missing columns: {sorted(missing)}")

    existing = {
        emp.emp_code: emp for emp in (await session.execute(select(Employee))).scalars().all()
    }

    # Two passes, because reporting_manager_code is a self-referential foreign key and
    # foreign_keys=ON is enabled. Inserting NX-4471 before its manager NX-2210 exists would be
    # rejected, and the CSV is not in dependency order.
    for row in rows:
        code = row["emp_code"].strip()
        employee = existing.get(code)
        if employee is None:
            employee = Employee(emp_code=code)
            session.add(employee)
            existing[code] = employee

        employee.name = row["name"].strip()
        employee.email = row["email"].strip()
        employee.designation = row["designation"].strip()
        employee.department = row["department"].strip()
        employee.cost_centre = row["cost_centre"].strip()
        employee.city = row["city"].strip()
        employee.role = Role(row["role"].strip())
        employee.reporting_manager_code = None

    await session.flush()

    for row in rows:
        manager_code = row["reporting_manager_code"].strip()
        # Empty for the MD, which is also how the chain walk knows where to stop.
        existing[row["emp_code"].strip()].reporting_manager_code = manager_code or None

    await session.flush()
    logger.info("Seeded %d employees from %s", len(rows), csv_path.name)
    return len(rows)
