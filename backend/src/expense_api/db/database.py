"""Engine, session factory, and the request-scoped session dependency.

The SQLite pragmas that make foreign keys and WAL work are registered in this package's
__init__.py, against the Engine class, so they apply to Alembic's engine and every test
fixture's engine too - not only this one. See db/__init__.py for why that matters.
"""

import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from expense_api.config.settings import settings

logger = logging.getLogger(__name__)

# SQLite will not create a missing parent directory.
settings.database_path.parent.mkdir(parents=True, exist_ok=True)

# No pool tuning: SQLite serialises writers, so a large pool buys nothing and mostly produces
# "database is locked" under load instead of waiting politely (see busy_timeout).
engine = create_async_engine(settings.database_url, echo=False)

# expire_on_commit=False so objects stay readable after commit; a FastAPI handler routinely
# serialises a model it has just written, and the default would re-fetch every attribute.
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session
