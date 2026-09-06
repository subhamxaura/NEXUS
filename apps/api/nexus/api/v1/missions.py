"""Mission endpoints: create/run, inspect, events, cancel. All ownership-checked."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.v1.deps import get_current_user, get_owned_repo
from nexus.core.database import get_session
from nexus.models.entities import (
    AgentEvent,
    Mission,
    Patch,
    PullRequest,
    Repository,
    Review,
    Task,
    User,
    ValidationRun,
)
from nexus.services import missions as mission_service
from nexus.services import pr as pr_service

router = APIRouter(tags=["missions"])


class MissionIn(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    finding_id: int | None = None


class TaskOut(BaseModel):
    id: int
    agent_name: str
    status: str
    dependencies: list[str]
    input: dict[str, object]
    output: dict[str, object]
    token_usage: dict[str, object]
    duration_ms: int
    attempt_count: int
    model: str
    prompt_version: str
    error: str | None


class MissionOut(BaseModel):
    id: int
    repo_id: int
    goal: str
    finding_id: int | None
    status: str
    plan: dict[str, object]
    result: dict[str, object]


class EventOut(BaseModel):
    id: int
    task_id: int | None
    event_type: str
    payload: dict[str, object]
    created_at: str


class PatchOut(BaseModel):
    id: int
    diff: str
    files_changed: list[str]
    rationale: str
    applied_state: str


class ApproveIn(BaseModel):
    github_token: str = Field(default="", max_length=255)


class PullRequestOut(BaseModel):
    pr_number: int
    url: str
    branch: str
    base: str
    state: str


def _mission_out(mission: Mission) -> MissionOut:
    return MissionOut(
        id=mission.id,
        repo_id=mission.repo_id,
        goal=mission.goal,
        finding_id=mission.finding_id,
        status=mission.status,
        plan=dict(mission.plan),
        result=dict(mission.result),
    )


def _task_out(task: Task) -> TaskOut:
    return TaskOut(
        id=task.id,
        agent_name=task.agent_name,
        status=task.status,
        dependencies=list(task.dependencies),
        input=dict(task.input),
        output=dict(task.output),
        token_usage=dict(task.token_usage),
        duration_ms=task.duration_ms,
        attempt_count=task.attempt_count,
        model=task.model,
        prompt_version=task.prompt_version,
        error=task.error,
    )


async def _owned_mission(mission_id: int, user: User, session: AsyncSession) -> Mission:
    result = await session.execute(select(Mission).where(Mission.id == mission_id))
    mission = result.scalars().first()
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found")
    repo = await session.get(Repository, mission.repo_id)
    if repo is None or repo.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="mission not found")
    return mission


@router.post("/repos/{repo_id}/missions", response_model=MissionOut)
async def start_mission(
    repo_id: int,
    body: MissionIn,
    repo: Repository = Depends(get_owned_repo),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MissionOut:
    _ = repo_id
    try:
        mission = await mission_service.create_mission(
            session, repo, user, body.goal, body.finding_id
        )
    except mission_service.MissionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    mission = await mission_service.run_mission(session, mission.id)
    return _mission_out(mission)


@router.get("/repos/{repo_id}/missions", response_model=list[MissionOut])
async def list_missions(
    repo_id: int,
    repo: Repository = Depends(get_owned_repo),
    session: AsyncSession = Depends(get_session),
) -> list[MissionOut]:
    _ = repo_id
    result = await session.execute(
        select(Mission).where(Mission.repo_id == repo.id).order_by(Mission.id.desc())
    )
    return [_mission_out(m) for m in result.scalars().all()]


@router.get("/missions/{mission_id}")
async def mission_detail(
    mission_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    mission = await _owned_mission(mission_id, user, session)
    tasks = await session.execute(
        select(Task).where(Task.mission_id == mission.id).order_by(Task.id)
    )
    patch = await session.execute(select(Patch).where(Patch.mission_id == mission.id))
    patch_row = patch.scalars().first()
    validations: list[dict[str, object]] = []
    review_out: dict[str, object] | None = None
    if patch_row:
        runs = await session.execute(
            select(ValidationRun)
            .where(ValidationRun.patch_id == patch_row.id)
            .order_by(ValidationRun.id)
        )
        validations = [
            {
                "id": r.id,
                "command": r.command,
                "exit_code": r.exit_code,
                "status": r.status,
                "log_tail": r.log_tail,
                "test_counts": dict(r.test_counts),
                "duration_s": r.duration_s,
                "sandbox_id": r.sandbox_id,
            }
            for r in runs.scalars().all()
        ]
        review = await session.execute(select(Review).where(Review.patch_id == patch_row.id))
        review_row = review.scalars().first()
        if review_row:
            review_out = {
                "verdict": review_row.verdict,
                "score": review_row.score,
                "comments": list(review_row.comments),
                "concerns": list(review_row.concerns),
                "diff_hash": review_row.diff_hash,
            }
    pr_row = (
        (await session.execute(select(PullRequest).where(PullRequest.mission_id == mission.id)))
        .scalars()
        .first()
    )
    return {
        "mission": _mission_out(mission).model_dump(),
        "tasks": [_task_out(t).model_dump() for t in tasks.scalars().all()],
        "patch": PatchOut(
            id=patch_row.id,
            diff=patch_row.diff,
            files_changed=list(patch_row.files_changed),
            rationale=patch_row.rationale,
            applied_state=patch_row.applied_state,
        ).model_dump()
        if patch_row
        else None,
        "validation_runs": validations,
        "review": review_out,
        "pull_request": PullRequestOut(
            pr_number=pr_row.pr_number,
            url=pr_row.url,
            branch=pr_row.branch,
            base=pr_row.base,
            state=pr_row.state,
        ).model_dump()
        if pr_row
        else None,
    }


@router.get("/missions/{mission_id}/events", response_model=list[EventOut])
async def mission_events(
    mission_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[EventOut]:
    mission = await _owned_mission(mission_id, user, session)
    result = await session.execute(
        select(AgentEvent)
        .where(AgentEvent.mission_id == mission.id)
        .order_by(AgentEvent.id)
        .limit(2000)
    )
    return [
        EventOut(
            id=e.id,
            task_id=e.task_id,
            event_type=e.event_type,
            payload=dict(e.payload),
            created_at=e.created_at.isoformat() if e.created_at else "",
        )
        for e in result.scalars().all()
    ]


@router.post("/missions/{mission_id}/cancel", response_model=MissionOut)
async def cancel_mission(
    mission_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MissionOut:
    mission = await _owned_mission(mission_id, user, session)
    try:
        mission = await mission_service.cancel_mission(session, mission)
    except mission_service.MissionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _mission_out(mission)


@router.post("/missions/{mission_id}/retry", response_model=MissionOut)
async def retry_mission(
    mission_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MissionOut:
    """Re-run a needs_human/failed/cancelled mission. Appends new tasks to the trace."""
    mission = await _owned_mission(mission_id, user, session)
    if mission.status not in ("needs_human", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"cannot retry a {mission.status} mission")
    mission = await mission_service.run_mission(session, mission.id)
    return _mission_out(mission)


@router.post("/missions/{mission_id}/approve", response_model=PullRequestOut)
async def approve_mission(
    mission_id: int,
    body: ApproveIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PullRequestOut:
    mission = await _owned_mission(mission_id, user, session)
    try:
        pr = await pr_service.approve_mission(session, mission.id, body.github_token or None)
    except mission_service.MissionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return PullRequestOut(
        pr_number=pr.pr_number, url=pr.url, branch=pr.branch, base=pr.base, state=pr.state
    )
