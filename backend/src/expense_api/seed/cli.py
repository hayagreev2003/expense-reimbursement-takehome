"""Seed entrypoint: `python -m expense_api.seed.cli`.

Safe to run repeatedly. Called by `make seed`, by `make reset-db`, and by the container
entrypoint on start.
"""

import asyncio
import logging
import sys

from expense_api.config.logging_config import setup_logging
from expense_api.config.settings import settings
from expense_api.db.database import async_session_maker
from expense_api.seed.employees import seed_employees
from expense_api.seed.policy import seed_policy_versions

logger = logging.getLogger(__name__)


async def run_seed() -> tuple[int, int]:
    async with async_session_maker() as session:
        employees = await seed_employees(session, settings.pack_dir / "employee_master.csv")
        policies = await seed_policy_versions(session)
        await session.commit()
    return employees, policies


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
