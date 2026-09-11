"""Shared test fixtures.

Environment defaults are set before any expense_api import, because Settings is instantiated at
module scope. A test run must not depend on a developer's .env file, and must never open the
development database.
"""

import os
import subprocess
import tempfile
from pathlib import Path

# Must run before expense_api is imported anywhere. Existing values win, so a developer pointing
# at something specific is not silently overridden.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")

# A throwaway file per run, outside the repo. The dev database lives at backend/data/expense.db
# and no test should be able to reach it, however a fixture is later mis-wired.
_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="expense-test-"))
os.environ.setdefault("DATABASE_PATH", str(_TEST_DB_DIR / "expense_test.db"))

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from expense_api.config.settings import BACKEND_ROOT, settings  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _never_touch_the_development_database() -> None:
    """Fail the whole run rather than write to backend/data/expense.db.

    conftest redirects DATABASE_PATH above, but that only helps if it actually took effect
    before Settings was constructed. Asserting it here turns a silent import-order regression
    into an immediate, obvious failure instead of a corrupted development database.
    """
    resolved = settings.database_path.resolve()
    assert resolved.is_relative_to(_TEST_DB_DIR), (
        f"Tests are pointed at {resolved}, not the temp directory. "
        "DATABASE_PATH was read before conftest set it."
    )
    assert not resolved.is_relative_to((BACKEND_ROOT / "data").resolve())


@pytest.fixture(scope="session")
def migrated_database(_never_touch_the_development_database: None) -> Path:
    """Build the test schema with Alembic, not `create_all`.

    Slower by a second, and worth it: the append-only triggers on claim_event exist only in the
    migration. A schema built from metadata would let every audit-immutability test pass
    against a table that is in fact mutable.
    """
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        env={**os.environ, "DATABASE_PATH": str(settings.database_path)},
    )
    return settings.database_path


@pytest_asyncio.fixture
async def db_connection(migrated_database: Path) -> AsyncIterator[AsyncConnection]:
    """A connection inside a transaction that is always rolled back."""
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """The default. Anything written here disappears at the end of the test."""
    # create_savepoint lets code under test call commit() and still be rolled back by the outer
    # transaction. Without it, a service that commits would leak state into the next test.
    maker = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def db_session_maker(
    db_connection: AsyncConnection,
) -> async_sessionmaker[AsyncSession]:
    """For code that opens its own sessions. Still rolled back."""
    return async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


@pytest_asyncio.fixture
async def committing_session_maker(
    migrated_database: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Independent connections that really commit. For concurrency tests only.

    Rollback isolation hides contention, so a test about two approvers acting at once has to
    write for real. Tables are emptied on teardown.
    """
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await _truncate_all(engine)
        await engine.dispose()


async def _truncate_all(engine) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from expense_api.db.models import Base

    async with engine.begin() as connection:
        # Triggers block DELETE on claim_event, so drop them for the duration of the cleanup.
        await connection.execute(text("DROP TRIGGER IF EXISTS claim_event_no_delete"))
        await connection.execute(text("DROP TRIGGER IF EXISTS claim_event_no_update"))
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(text(f"DELETE FROM {table.name}"))  # noqa: S608
        await connection.execute(
            text(
                "CREATE TRIGGER claim_event_no_update BEFORE UPDATE ON claim_event "
                "BEGIN SELECT RAISE(ABORT, 'claim_event is append-only: UPDATE is not "
                "permitted'); END"
            )
        )
        await connection.execute(
            text(
                "CREATE TRIGGER claim_event_no_delete BEFORE DELETE ON claim_event "
                "BEGIN SELECT RAISE(ABORT, 'claim_event is append-only: DELETE is not "
                "permitted'); END"
            )
        )


@pytest.fixture
def app():  # type: ignore[no-untyped-def]
    from expense_api.main import create_app

    return create_app()


# asyncio_mode is strict, so an async fixture must be declared with pytest_asyncio.fixture.
@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
