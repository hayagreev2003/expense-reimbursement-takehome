"""Database package.

The SQLite pragma listener lives here, not in database.py, and that placement is deliberate.

These pragmas must apply to *every* connection, not just the application engine's. Alembic
builds its own engine, and so does every test fixture. Registering the listener in database.py
meant it only ran for code that had imported that specific module - so migrations and tests
silently ran without foreign key enforcement, and the test asserting referential integrity
passed while proving nothing.

Importing anything from `expense_api.db` executes this module first, which makes registration
unconditional for anyone who touches the database at all.
"""

import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import ConnectionPoolEntry

logger = logging.getLogger(__name__)


def _is_sqlite(dbapi_connection: object) -> bool:
    """Detect SQLite across both the sync driver and the async adapter.

    The obvious check - `type(conn).__module__.split(".")[0] in ("sqlite3", "aiosqlite")` -
    is wrong, and wrong in the silent direction. Under aiosqlite, SQLAlchemy hands the listener
    its own wrapper: module `sqlalchemy.dialects.sqlite.aiosqlite`, class
    `AsyncAdapt_aiosqlite_connection`. The first path segment is "sqlalchemy", so that check
    skipped every connection and left `PRAGMA foreign_keys` at 0 everywhere - application
    included.

    Matching "sqlite" anywhere in the module path or the class name covers sqlite3 (module
    "sqlite3"), aiosqlite's raw connection (module "aiosqlite.core"), and the adapter (both).
    """
    cls = type(dbapi_connection)
    return "sqlite" in cls.__module__.lower() or "sqlite" in cls.__name__.lower()


@event.listens_for(Engine, "connect")
def _apply_sqlite_pragmas(dbapi_connection: Any, _record: ConnectionPoolEntry) -> None:
    """Three pragmas, none of them optional for correctness.

    `foreign_keys=ON` - SQLite ignores foreign key constraints unless asked, per connection.
    Without it every ForeignKey in models.py is decoration and a delete orphans its children.

    `journal_mode=WAL` - lets readers proceed while a writer holds the write lock. Under the
    default rollback journal a single approval transaction blocks every concurrent read, so the
    approver queue appears to hang under exactly the contention it exists to handle.

    `busy_timeout` - wait for a held write lock rather than failing instantly with
    "database is locked".
    """
    # This listener sees every Engine in the process, including any non-SQLite one a later
    # change introduces, and these statements are SQLite-only.
    if not _is_sqlite(dbapi_connection):
        return

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()
