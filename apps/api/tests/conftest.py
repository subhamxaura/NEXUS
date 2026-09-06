"""Test DB isolation: fresh SQLite schema per test (set before nexus imports)."""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./nexus_test.db"

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from nexus.core.database import Base

TEST_URL = "sqlite+aiosqlite:///./nexus_test.db"


@pytest_asyncio.fixture
async def _fresh_db():
    engine = create_async_engine(TEST_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()
    try:
        os.remove("nexus_test.db")
    except OSError:
        pass
