"""Wipe what the demo produced, then put the starting state back.

Deliberately *not* "drop the file and re-migrate": the engine holds open connections to that
file, and deleting it underneath them leaves the process talking to an unlinked inode that
still answers queries. Deleting rows is the thing that is actually observable.

Employees and policy versions survive the wipe. They are reference data seeded from the pack,
every approval step points at an employee row, and re-creating them would mint new primary keys
for no gain. The seed is idempotent over both, so re-running it after the wipe is a no-op there
and rebuilds only the trip, its advance and its inbox.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.claims import withdrawals
from expense_api.config.settings import settings
from expense_api.db.audit import CREATE_AUDIT_TRIGGERS, DROP_AUDIT_TRIGGERS
from expense_api.db.models import (
    Advance,
    ApprovalStep,
    ClaimEvent,
    ClaimLine,
    Employee,
    EvidenceDocument,
    ExtractedLineItem,
    Notification,
    PaymentRecord,
    PolicyDecision,
    PolicyVersion,
    SettlementClaim,
    TravelRequest,
    TravelRequestEstimateLine,
)
from expense_api.demo.schemas import ResetDemoResponse
from expense_api.seed.cli import seed_all
from expense_api.seed.trip import TRQ_ID

logger = logging.getLogger(__name__)

# Children before parents. SQLite enforces foreign keys here (the PRAGMA is registered in
# db/__init__.py), so a wrong order fails loudly rather than orphaning rows - but several of
# these cascades exist only in the ORM, and an ORM cascade does not run for a bulk delete.
WIPE_ORDER = (
    ClaimEvent,
    Notification,
    PaymentRecord,
    ApprovalStep,
    PolicyDecision,
    ClaimLine,
    SettlementClaim,
    ExtractedLineItem,
    EvidenceDocument,
    Advance,
    TravelRequestEstimateLine,
    TravelRequest,
)


def _clear_uploads() -> int:
    """Remove every uploaded file. Returns how many there were.

    Scoped to `settings.upload_dir`, which is the application's own directory and never the
    pack - the pack is the specification and is mounted read-only.
    """
    root = settings.upload_dir
    if not root.exists():
        return 0

    removed = sum(1 for path in root.rglob("*") if path.is_file())
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    return removed


async def _run(session: AsyncSession, statements: tuple[str, ...]) -> None:
    for statement in statements:
        await session.execute(text(statement))


async def reset_demo(session: AsyncSession) -> ResetDemoResponse:
    """Wipe and re-seed.

    `claim_event` is append-only by database trigger, so the guard comes off for the length of
    the wipe and goes back on in a `finally` - a reset that failed halfway must not leave the
    audit trail writable. The drop happens before the first delete rather than alongside it
    because the sqlite3 driver commits around DDL, and doing it later would commit a
    half-finished wipe.
    """
    await _run(session, DROP_AUDIT_TRIGGERS)
    try:
        deleted = 0
        for model in WIPE_ORDER:
            # CursorResult, because a bulk delete is a DML statement; the base Result that
            # execute() is typed as does not carry a row count.
            result = cast(CursorResult[Any], await session.execute(delete(model)))
            deleted += result.rowcount or 0

        employees, policies = await seed_all(session)
        await session.commit()
    finally:
        # A no-op after a successful commit; after a failure it clears the transaction so the
        # statements below can run at all.
        await session.rollback()
        await _run(session, CREATE_AUDIT_TRIGGERS)
        await session.commit()

    # Counted after the commit, from the database rather than from the seed's return value:
    # the seed reports what it wrote, and on a re-run that is zero even though the rows exist.
    employee_count = (
        await session.execute(select(func.count()).select_from(Employee))
    ).scalar_one()
    policy_count = (
        await session.execute(select(func.count()).select_from(PolicyVersion))
    ).scalar_one()

    deleted_uploads = _clear_uploads()

    # Withdrawals are per-process state, not rows (see claims/withdrawals.py). A reset that put
    # the database back but left one standing would produce a "fresh" demo whose held line is
    # already withdrawn - the claim submits straight away and the step the walkthrough exists to
    # show never happens.
    withdrawals.clear_all()

    logger.info(
        "Demo reset: %d rows deleted, %d uploads removed, seeded %d employees / %d policies",
        deleted,
        deleted_uploads,
        employees,
        policies,
    )

    return ResetDemoResponse(
        deleted_rows=deleted,
        deleted_uploads=deleted_uploads,
        employees=employee_count,
        policy_versions=policy_count,
        trq_id=TRQ_ID,
    )
