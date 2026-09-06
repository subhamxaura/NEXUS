"""arq worker settings (Phase 0: no jobs yet; Phase 1 adds analyze)."""

from typing import Any

from arq.connections import RedisSettings

from nexus.core.config import settings


async def _noop(ctx: dict[str, Any]) -> dict[str, str]:
    return {"status": "ok"}


class WorkerSettings:
    functions = [_noop]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
