"""arq jobs: repository analysis. API runs inline when Redis is unreachable."""

from typing import Any

from arq.connections import RedisSettings
from sqlalchemy import select

from nexus.core.config import settings
from nexus.core.database import SessionLocal
from nexus.github import clone as gitclone
from nexus.models.entities import Analysis, Repository
from nexus.services import analysis as analysis_service


async def analyze_repo_job(ctx: dict[str, Any], analysis_id: int) -> dict[str, Any]:
    _ = ctx
    async with SessionLocal() as session:
        result = await session.execute(select(Analysis).where(Analysis.id == analysis_id))
        analysis = result.scalars().first()
        if analysis is None:
            return {"status": "missing"}
        repo = await session.get(Repository, analysis.repo_id)
        if repo is None:
            return {"status": "missing"}
        if analysis.status in ("complete", "partial"):
            return {"status": "cached", "analysis_id": analysis.id}
        try:
            outcome = await analysis_service.run_analysis(session, repo)
        except gitclone.CloneError as e:
            analysis.status = "failed"
            analysis.metrics = {"error": str(e)}
            await session.commit()
            return {"status": "failed", "error": str(e)}
        return {
            "status": outcome.analysis.status,
            "cache_hit": outcome.cache_hit,
            "analysis_id": outcome.analysis.id,
        }


async def run_mission_job(ctx: dict[str, Any], mission_id: int) -> dict[str, Any]:
    """Worker-side mission execution (used in Compose; API runs inline in Phase 2)."""
    _ = ctx
    from nexus.services import missions as mission_service

    async with SessionLocal() as session:
        mission = await mission_service.run_mission(session, mission_id)
        return {"status": mission.status, "mission_id": mission.id}


async def _noop(ctx: dict[str, Any]) -> dict[str, str]:
    _ = ctx
    return {"status": "ok"}


class WorkerSettings:
    functions = [analyze_repo_job, run_mission_job, _noop]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
