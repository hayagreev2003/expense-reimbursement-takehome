"""Which draft lines the employee has withdrawn.

Per-process state for this build, not a table. Persisting a withdrawal belongs with the
SettlementClaim row, and this module is deliberately small and obvious so that move is a
contained change rather than an archaeology exercise. Two consequences to know about: a restart
forgets every withdrawal, and a second worker never sees the first one's.

It lives here rather than as a private dict in the router because it is state with a lifecycle -
the demo reset has to clear it, and a reset that puts the database back but leaves a withdrawal
standing produces a "fresh" demo whose held line is already gone.
"""

from __future__ import annotations

_WITHDRAWN: dict[str, set[str]] = {}


def record(trq_id: str, description: str) -> None:
    _WITHDRAWN.setdefault(trq_id, set()).add(description)


def for_trip(trq_id: str) -> frozenset[str]:
    return frozenset(_WITHDRAWN.get(trq_id, set()))


def clear_all() -> None:
    """Forget every withdrawal. The demo reset, and nothing else."""
    _WITHDRAWN.clear()
