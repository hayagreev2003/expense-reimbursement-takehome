"""Shared test fixtures.

Environment defaults are set before any expense_api import, because Settings is instantiated at
module scope. A test run must not depend on a developer's .env file, and must never open the
development database.

Database fixtures arrive with the schema in Unit 2.
"""

import os
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
