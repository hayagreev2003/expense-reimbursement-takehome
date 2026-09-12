"""Seed entrypoint: `python -m expense_api.seed.cli`.

Safe to run repeatedly. Called by `make seed`, by `make reset-db`, and by the container
entrypoint on start.
"""

import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.config.logging_config import setup_logging
from expense_api.config.settings import settings
from expense_api.db.database import async_session_maker
from expense_api.seed.employees import seed_employees
from expense_api.seed.policy import seed_policy_versions
from expense_api.seed.trip import seed_anchor_trip

logger = logging.getLogger(__name__)


async def seed_all(session: AsyncSession) -> tuple[int, int]:
    """Every seed step, against a caller-supplied session. Does not commit.

    Split out from `run_seed` so the demo reset can wipe and re-seed inside one transaction on
    one connection. SQLite serialises writers, so a reset that deleted on the request session
    and then re-seeded on a second one would be waiting on a lock it holds itself.
    """
    employees = await seed_employees(session, settings.pack_dir / "employee_master.csv")
    policies = await seed_policy_versions(session)
    await seed_anchor_trip(session)
    return employees, policies


async def run_seed() -> tuple[int, int]:
    async with async_session_maker() as session:
        counts = await seed_all(session)
        await session.commit()
    return counts


def main() -> int:
    setup_logging(settings.log_level)
    try:
        employees, policies = asyncio.run(run_seed())
    except Exception:
        logger.exception("Seed failed")
        return 1

    logger.info("Seed complete: %d employees, %d policy versions", employees, policies)
    return 0


if __name__ == "__main__":
    sys.exit(main())
