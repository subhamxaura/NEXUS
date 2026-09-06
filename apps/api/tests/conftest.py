"""Test DB isolation: fresh SQLite schema per test (set before nexus imports)."""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./nexus_test.db"

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from nexus.core.database import Base

# Import models so Base.metadata is populated no matter which test modules
# are collected (otherwise create_all is a silent no-op).
from nexus.models import entities  # noqa: F401

TEST_URL = "sqlite+aiosqlite:///./nexus_test.db"


@pytest_asyncio.fixture
async def _fresh_db():
    engine = create_async_engine(TEST_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()
    # Release pooled file handles first: on Windows, removing an open
    # SQLite file silently fails and leaks state into the next test.
    from nexus.core.database import engine as app_engine

    await app_engine.dispose()
    try:
        os.remove("nexus_test.db")
    except OSError:
        pass
