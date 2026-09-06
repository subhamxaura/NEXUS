"""Repository + analysis endpoints (all require ownership)."""

import posixpath

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.v1.deps import get_current_user, get_owned_repo
from nexus.core.database import get_session
from nexus.core.security import verify_webhook_signature  # noqa: F401 (wired in Phase 3)
from nexus.github import clone as gitclone
from nexus.intelligence.findings import guidance_for
from nexus.models.entities import Analysis, DependencyEdge, FileMetric, Finding, Repository, User
from nexus.services import analysis as analysis_service

router = APIRouter(tags=["repos"])

MAX_FILE_BYTES = 256_000


class RepoIn(BaseModel):
    owner: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)


class RepoOut(BaseModel):
    id: int
    owner: str
    name: str
    default_branch: str
    last_analyzed_sha: str | None


class FindingOut(BaseModel):
    id: int
    type: str
    severity: str
    path: str
    line: int | None
    message: str
    rule_id: str
    evidence: dict[str, object]
    priority_score: float
    guidance: dict[str, str] = {}


class FileOut(BaseModel):
    path: str
    language: str
    loc: int
    complexity: float
    maintainability: float | None
    churn: int
    test_presence: float
    risk_score: float
    in_degree: int
    out_degree: int
    risk_contributors: dict[str, float] = {}


class AnalysisOut(BaseModel):
    id: int
    commit_sha: str
    status: str
    health_score: float | None
    metrics: dict[str, object]
    analyzer_version: str
    cache_hit: bool = False


class EdgeOut(BaseModel):
    src_path: str
    dst_path: str
    kind: str


def _repo_out(repo: Repository) -> RepoOut:
    return RepoOut(
        id=repo.id,
        owner=repo.owner,
        name=repo.name,
        default_branch=repo.default_branch,
        last_analyzed_sha=repo.last_analyzed_sha,
    )


def resolve_repo_path(path: str) -> str:
    """Normalize a repo-relative path or raise ValueError (traversal guard)."""
    normalized = posixpath.normpath(path)
    if normalized.startswith("..") or posixpath.isabs(normalized) or normalized == ".":
        raise ValueError("invalid path")
    return normalized


@router.post("/repos", response_model=RepoOut, status_code=201)
async def connect_repo(
    body: RepoIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RepoOut:
    try:
        gitclone.validate_owner_name(body.owner.strip(), body.name.strip())
    except gitclone.CloneError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    owner, name = body.owner.strip(), body.name.strip().removesuffix(".git")
    existing = await session.execute(
        select(Repository).where(
            Repository.owner == owner, Repository.name == name, Repository.owner_user_id == user.id
        )
    )
    row = existing.scalars().first()
    if row is not None:
        return _repo_out(row)
    repo = Repository(owner=owner, name=name, owner_user_id=user.id)
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return _repo_out(repo)


@router.get("/repos", response_model=list[RepoOut])
async def list_repos(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[RepoOut]:
    result = await session.execute(
        select(Repository).where(Repository.owner_user_id == user.id).order_by(Repository.id.desc())
    )
    return [_repo_out(r) for r in result.scalars().all()]


async def _analysis_out(session: AsyncSession, analysis: Analysis, cache_hit: bool) -> AnalysisOut:
    return AnalysisOut(
        id=analysis.id,
        commit_sha=analysis.commit_sha,
        status=analysis.status,
        health_score=analysis.health_score,
        metrics=dict(analysis.metrics),
        analyzer_version=analysis.analyzer_version,
        cache_hit=cache_hit,
    )


@router.post("/repos/{repo_id}/analyze", response_model=AnalysisOut)
async def analyze_repo(
    repo_id: int,
    repo: Repository = Depends(get_owned_repo),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    _ = repo_id
    try:
        outcome = await analysis_service.run_analysis(session, repo)
    except gitclone.CloneError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return await _analysis_out(session, outcome.analysis, outcome.cache_hit)


@router.get("/repos/{repo_id}/analysis/latest", response_model=AnalysisOut)
async def latest_analysis(
    repo_id: int,
    repo: Repository = Depends(get_owned_repo),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    _ = repo_id
    if repo.last_analyzed_sha is None:
        raise HTTPException(status_code=404, detail="no analysis yet")
    cached = await analysis_service.find_cached(session, repo.id, repo.last_analyzed_sha)
    if cached is None:
        raise HTTPException(status_code=404, detail="no analysis yet")
    return await _analysis_out(session, cached, True)


async def _require_analysis(session: AsyncSession, repo: Repository) -> Analysis:
    if repo.last_analyzed_sha is None:
        raise HTTPException(status_code=404, detail="no analysis yet")
    cached = await analysis_service.find_cached(session, repo.id, repo.last_analyzed_sha)
    if cached is None:
        raise HTTPException(status_code=404, detail="no analysis yet")
    return cached


@router.get("/repos/{repo_id}/findings", response_model=list[FindingOut])
async def list_findings(
    repo_id: int,
    repo: Repository = Depends(get_owned_repo),
    session: AsyncSession = Depends(get_session),
) -> list[FindingOut]:
    _ = repo_id
    analysis = await _require_analysis(session, repo)
    result = await session.execute(
        select(Finding)
        .where(Finding.analysis_id == analysis.id)
        .order_by(Finding.priority_score.desc(), Finding.id)
        .limit(500)
    )
    out: list[FindingOut] = []
    for f in result.scalars().all():
        guidance = guidance_for(f.rule_id)
        out.append(
            FindingOut(
                id=f.id,
                type=f.type,
                severity=f.severity,
                path=f.path,
                line=f.line,
                message=f.message,
                rule_id=f.rule_id,
                evidence=dict(f.evidence),
                priority_score=f.priority_score,
                guidance={"why": guidance.why, "fix": guidance.fix} if guidance else {},
            )
        )
    return out


@router.get("/repos/{repo_id}/files", response_model=list[FileOut])
async def list_files(
    repo_id: int,
    repo: Repository = Depends(get_owned_repo),
    session: AsyncSession = Depends(get_session),
) -> list[FileOut]:
    _ = repo_id
    analysis = await _require_analysis(session, repo)
    contributors = analysis.metrics.get("risk_contributors", {})
    if not isinstance(contributors, dict):
        contributors = {}
    result = await session.execute(
        select(FileMetric)
        .where(FileMetric.analysis_id == analysis.id)
        .order_by(FileMetric.risk_score.desc(), FileMetric.path)
        .limit(2000)
    )
    out: list[FileOut] = []
    for m in result.scalars().all():
        contrib = contributors.get(m.path, {})
        out.append(
            FileOut(
                path=m.path,
                language=m.language,
                loc=m.loc,
                complexity=m.complexity,
                maintainability=m.maintainability,
                churn=m.churn,
                test_presence=m.test_presence,
                risk_score=m.risk_score,
                in_degree=m.in_degree,
                out_degree=m.out_degree,
                risk_contributors=dict(contrib) if isinstance(contrib, dict) else {},
            )
        )
    return out


@router.get("/repos/{repo_id}/graph")
async def repo_graph(
    repo_id: int,
    repo: Repository = Depends(get_owned_repo),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _ = repo_id
    analysis = await _require_analysis(session, repo)
    edges = await session.execute(
        select(DependencyEdge).where(DependencyEdge.analysis_id == analysis.id).limit(5000)
    )
    nodes = await session.execute(
        select(FileMetric.path, FileMetric.risk_score).where(FileMetric.analysis_id == analysis.id)
    )
    return {
        "nodes": [{"path": p, "risk": r} for p, r in nodes.all()],
        "edges": [
            {"src": e.src_path, "dst": e.dst_path, "kind": e.kind} for e in edges.scalars().all()
        ],
    }


@router.get("/repos/{repo_id}/files/{path:path}")
async def read_file(
    repo_id: int,
    path: str,
    repo: Repository = Depends(get_owned_repo),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _ = (repo_id, session)
    try:
        normalized = resolve_repo_path(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if repo.last_analyzed_sha is None:
        raise HTTPException(status_code=404, detail="no analysis yet")
    try:
        workspace = analysis_service.ensure_workspace(repo, repo.last_analyzed_sha)
    except gitclone.CloneError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    target = workspace / normalized
    try:
        data = target.read_bytes()
    except OSError:
        raise HTTPException(status_code=404, detail="file not found") from None
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="file too large to preview")
    if b"\x00" in data[:8192]:
        raise HTTPException(status_code=415, detail="binary file preview not supported")
    return {"path": normalized, "content": data.decode("utf-8", errors="replace")}
