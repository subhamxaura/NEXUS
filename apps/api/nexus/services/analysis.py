"""Analysis service: cache lookup, pipeline execution, persistence.

Cache key: (repo_id, commit_sha, analyzer_version). A completed/partial row
for the same key is returned as-is (cache hit) — never recomputed.
"""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.config import settings
from nexus.github import clone as gitclone
from nexus.intelligence.pipeline import PipelineResult, run_pipeline
from nexus.models.entities import Analysis, DependencyEdge, FileMetric, Finding, Repository

VALID_STATUSES = ("pending", "running", "complete", "partial", "failed")


@dataclass(frozen=True)
class AnalysisOutcome:
    analysis: Analysis
    cache_hit: bool


async def find_cached(session: AsyncSession, repo_id: int, sha: str) -> Analysis | None:
    stmt = (
        select(Analysis)
        .where(
            Analysis.repo_id == repo_id,
            Analysis.commit_sha == sha,
            Analysis.analyzer_version == settings.analyzer_version,
        )
        .order_by(Analysis.id.desc())
    )
    result = await session.execute(stmt)
    row = result.scalars().first()
    if row is not None and row.status in ("complete", "partial"):
        return row
    return None


def _persist(result: PipelineResult, analysis: Analysis) -> None:
    status = (
        "partial"
        if (
            result.skipped
            or result.file_count == 0
            or any(f.type == "parse-error" for f in result.findings)
        )
        else "complete"
    )
    analysis.status = status
    analysis.health_score = result.health
    analysis.metrics = {
        "health_breakdown": result.health_breakdown,
        "availability": result.availability,
        "skipped": list(result.skipped),
        "file_count": result.file_count,
        "finding_count": len(result.findings),
    }


async def _clear_children(session: AsyncSession, analysis_id: int) -> None:
    for model in (Finding, DependencyEdge, FileMetric):
        await session.execute(delete(model).where(model.analysis_id == analysis_id))


async def run_analysis(
    session: AsyncSession,
    repo: Repository,
    source_dir: Path | None = None,
) -> AnalysisOutcome:
    """Clone (unless `source_dir` given, used by tests), run pipeline, persist."""
    workdir: Path | None = None
    if source_dir is None:
        cloned = gitclone.clone(gitclone.repo_url(repo.owner, repo.name))
        workdir = cloned.workdir
        sha = cloned.sha
        workspace = cloned.workdir
    else:
        workspace = source_dir
        sha = "test-sha"

    try:
        cached = await find_cached(session, repo.id, sha)
        if cached is not None:
            if cached.metrics.get("file_count", 1) > 0:
                repo.last_analyzed_sha = sha
                await session.commit()
                await session.refresh(cached)
                return AnalysisOutcome(analysis=cached, cache_hit=True)
            # Zero-file shell: drop it so a corrected analyzer result is
            # recomputed and persisted instead of masked (unique key).
            await session.delete(cached)
            await session.flush()

        analysis = Analysis(
            repo_id=repo.id,
            commit_sha=sha,
            status="running",
            analyzer_version=settings.analyzer_version,
        )
        session.add(analysis)
        await session.flush()

        try:
            result = run_pipeline(workspace)
        except Exception as e:
            analysis.status = "failed"
            analysis.metrics = {"error": f"{type(e).__name__}: {e}"}
            repo.last_analyzed_sha = None
            await session.commit()
            await session.refresh(analysis)
            return AnalysisOutcome(analysis=analysis, cache_hit=False)

        await _clear_children(session, analysis.id)
        _persist(result, analysis)
        for fr in result.files:
            session.add(
                FileMetric(
                    analysis_id=analysis.id,
                    path=fr.path,
                    language=fr.language,
                    loc=fr.loc,
                    complexity=fr.complexity,
                    maintainability=fr.maintainability,
                    churn=fr.churn,
                    test_presence=fr.test_presence,
                    risk_score=fr.risk,
                    in_degree=fr.in_degree,
                    out_degree=fr.out_degree,
                )
            )
        for src, dst, kind in result.edges:
            session.add(
                DependencyEdge(analysis_id=analysis.id, src_path=src, dst_path=dst, kind=kind)
            )
        for f in result.findings:
            session.add(
                Finding(
                    analysis_id=analysis.id,
                    type=f.type,
                    severity=f.severity,
                    path=f.path,
                    line=f.line,
                    message=f.message,
                    rule_id=f.rule_id,
                    evidence=f.evidence,
                    priority_score=f.priority,
                )
            )
        # Store risk contributors alongside metrics for explainability.
        contributors = {fr.path: fr.risk_contributors for fr in result.files}
        metrics = dict(analysis.metrics)
        metrics["risk_contributors"] = contributors
        analysis.metrics = metrics
        repo.last_analyzed_sha = sha
        await session.commit()
        await session.refresh(analysis)
        return AnalysisOutcome(analysis=analysis, cache_hit=False)
    finally:
        if workdir is not None:
            gitclone.dispose(workdir)


_workspace_cache: dict[tuple[int, str], Path] = {}


def ensure_workspace(repo: Repository, sha: str) -> Path:
    """Reusable read-only-ish workspace for file reads (Phase 1; best-effort tmp)."""
    key = (repo.id, sha)
    cached = _workspace_cache.get(key)
    if cached is not None and cached.exists():
        return cached
    cloned = gitclone.clone(gitclone.repo_url(repo.owner, repo.name))
    if cloned.sha != sha:
        gitclone.dispose(cloned.workdir)
        raise gitclone.CloneError("upstream moved during read; re-analyze first")
    _workspace_cache[key] = cloned.workdir
    return cloned.workdir
