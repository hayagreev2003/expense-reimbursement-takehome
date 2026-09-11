"""Load authored policy YAML into effective-dated policy_version rows.

The YAML under policy/versions/ is the authored source; the row is what evaluation reads. That
indirection is the point: a claim records the version id it was evaluated against, so editing
the file later cannot retroactively change a settled claim's numbers.
"""

import logging
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.db.models import PolicyVersion

logger = logging.getLogger(__name__)

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "policy" / "versions"

_REQUIRED_KEYS = {
    "document_id",
    "revision",
    "effective_from",
    "approval_matrix",
    "lodging",
    "meals",
    "city_classes",
    "non_reimbursable",
    "submission",
}


def _coerce_date(value: Any, field: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    raise ValueError(f"{field} must be a date, got {value!r}")


async def seed_policy_versions(session: AsyncSession, versions_dir: Path = VERSIONS_DIR) -> int:
    paths = sorted(versions_dir.glob("*.yaml"))
    if not paths:
        raise FileNotFoundError(f"No policy version files found in {versions_dir}")

    count = 0
    for path in paths:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        missing = _REQUIRED_KEYS - set(payload)
        if missing:
            # Fail loudly. A policy version missing its approval matrix would otherwise produce
            # claims that route to nobody.
            raise ValueError(f"{path.name} is missing required keys: {sorted(missing)}")

        document_id = payload["document_id"]
        revision = payload["revision"]

        row = (
            await session.execute(
                select(PolicyVersion).where(
                    PolicyVersion.document_id == document_id,
                    PolicyVersion.revision == revision,
                )
            )
        ).scalar_one_or_none()

        if row is None:
            row = PolicyVersion(document_id=document_id, revision=revision)
            session.add(row)

        row.effective_from = _coerce_date(payload["effective_from"], "effective_from")  # type: ignore[assignment]
        row.effective_to = _coerce_date(payload.get("effective_to"), "effective_to")

        # YAML dates are date objects and JSON columns cannot hold them. Store ISO strings in
        # the payload; the typed columns above are what evaluation selects on anyway.
        row.payload = _stringify_dates(payload)
        count += 1

    await session.flush()
    logger.info("Seeded %d policy version(s) from %s", count, versions_dir.name)
    return count


def _stringify_dates(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _stringify_dates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify_dates(v) for v in value]
    return value
