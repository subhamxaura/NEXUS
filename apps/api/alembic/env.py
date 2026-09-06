"""Alembic env (async)."""

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from nexus.core.config import settings
from nexus.core.database import Base
from nexus.models import entities  # noqa: F401

config = context.config
target_metadata = Base.metadata


def _configure(conn) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=conn, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _migrate() -> None:
    engine = create_async_engine(settings.database_url, future=True)
    async with engine.connect() as conn:
        await conn.run_sync(_configure)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=settings.database_url, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_migrate())
