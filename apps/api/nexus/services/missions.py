"""Mission orchestration: deterministic DAG, state machine, events, diff gate.

Phase 2 DAG: orchestrator → scout → architect → security → coder.
Coder output must pass `git apply --check` (read-only) or the mission ends
as `needs_human`. No GitHub mutation happens in this phase.
"""

import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.agents.base import AgentFailure, BaseAgent
from nexus.agents.context import AgentContext
from nexus.agents.implementations import AGENTS, OrchestratorInput
from nexus.agents.schemas import (
    ArchitectInput,
    CoderInput,
    FileSummary,
    FindingSummary,
    MissionPlan,
    ScoutInput,
    SecurityInput,
)
from nexus.core.config import settings
from nexus.github import clone as gitclone
from nexus.llm.client import LLMClient, PermanentLLMError
from nexus.models.entities import (
    AgentEvent,
    Analysis,
    FileMetric,
    Finding,
    Mission,
    Patch,
    Repository,
    Task,
    User,
)
from nexus.services import analysis as analysis_service

MISSION_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "created": ("running", "cancelled"),
    "running": ("patch_ready", "needs_human", "failed", "cancelled"),
    "patch_ready": (),
    "needs_human": (),
    "failed": (),
    "cancelled": (),
}

TASK_RUN_ORDER = ("orchestrator", "scout", "architect", "security", "coder")
MAX_FILE_CONTENT_CHARS = 12000
MAX_CONTEXT_FILES = 6


class MissionError(RuntimeError):
    pass


def transition(mission: Mission, to: str) -> None:
    allowed = MISSION_TRANSITIONS.get(mission.status, ())
    if to not in allowed:
        raise MissionError(f"illegal transition {mission.status} -> {to}")
    mission.status = to


async def log_event(
    session: AsyncSession,
    mission_id: int,
    event_type: str,
    payload: dict[str, Any],
    task_id: int | None = None,
) -> None:
    session.add(
        AgentEvent(mission_id=mission_id, task_id=task_id, event_type=event_type, payload=payload)
    )
    await session.flush()


def check_diff(diff: str, workspace: Path) -> tuple[bool, str, list[str]]:
    """Read-only `git apply --check`. Returns (ok, message, files_changed)."""
    if not diff.strip() or "@@" not in diff:
        return False, "diff is empty or not a unified diff", []
    files: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            files.append(line.removeprefix("+++ b/").strip())
    # Normalize newlines: temp files on Windows translate \n -> \r\n in text
    # mode, which corrupts the patch. Write with newline="" for byte fidelity.
    normalized = diff.replace("\r\n", "\n").replace("\r", "\n")
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False, newline="") as tmp:
        tmp.write(normalized)
        tmp_path = tmp.name
    try:
        # Pin autocrlf=false: workstation git configs differ; the check must
        # validate literal bytes deterministically (prod containers use LF).
        proc = subprocess.run(  # noqa: S603 -- fixed git binary, validated args, no shell
            [  # noqa: S607 -- git binary from PATH
                "git",
                "-c",
                "core.autocrlf=false",
                "-C",
                str(workspace),
                "apply",
                "--check",
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"diff check could not run: {e}", files
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        err = (proc.stderr or "diff does not apply").strip()[:2000]
        return False, err, files
    return True, "diff applies cleanly", files


async def _latest_analysis(session: AsyncSession, repo: Repository) -> Analysis:
    if repo.last_analyzed_sha is None:
        raise MissionError("analyze the repository before starting a mission")
    analysis = await analysis_service.find_cached(session, repo.id, repo.last_analyzed_sha)
    if analysis is None:
        raise MissionError("analyze the repository before starting a mission")
    return analysis


async def create_mission(
    session: AsyncSession,
    repo: Repository,
    user: User,
    goal: str,
    finding_id: int | None = None,
) -> Mission:
    goal = goal.strip()
    if not goal or len(goal) > 2000:
        raise MissionError("goal must be 1-2000 characters")
    analysis = await _latest_analysis(session, repo)
    if finding_id is not None:
        found = await session.execute(
            select(Finding).where(Finding.id == finding_id, Finding.analysis_id == analysis.id)
        )
        if found.scalars().first() is None:
            raise MissionError("finding does not belong to the latest analysis")
    mission = Mission(
        repo_id=repo.id,
        analysis_id=analysis.id,
        finding_id=finding_id,
        goal=goal,
        status="created",
        creator_user_id=user.id,
    )
    session.add(mission)
    await session.flush()
    await log_event(
        session, mission.id, "mission_created", {"goal": goal, "finding_id": finding_id}
    )
    await session.commit()
    await session.refresh(mission)
    return mission


async def _summaries(
    session: AsyncSession, analysis: Analysis
) -> tuple[
    list[FileSummary],
    list[FindingSummary],
]:
    files = await session.execute(
        select(FileMetric)
        .where(FileMetric.analysis_id == analysis.id)
        .order_by(FileMetric.risk_score.desc())
        .limit(30)
    )
    top_files = [
        FileSummary(
            path=m.path,
            language=m.language,
            loc=m.loc,
            complexity=m.complexity,
            risk_score=m.risk_score,
        )
        for m in files.scalars().all()
    ]
    findings = await session.execute(
        select(Finding)
        .where(Finding.analysis_id == analysis.id)
        .order_by(Finding.priority_score.desc())
        .limit(20)
    )
    rows = findings.scalars().all()
    top_findings = [
        FindingSummary(
            id=f.id,
            type=f.type,
            severity=f.severity,
            path=f.path,
            line=f.line,
            message=f.message,
            rule_id=f.rule_id,
            priority_score=f.priority_score,
        )
        for f in rows
    ]
    return top_files, top_findings


async def _finding_summary(session: AsyncSession, finding_id: int | None) -> FindingSummary | None:
    if finding_id is None:
        return None
    row = await session.get(Finding, finding_id)
    if row is None:
        return None
    return FindingSummary(
        id=row.id,
        type=row.type,
        severity=row.severity,
        path=row.path,
        line=row.line,
        message=row.message,
        rule_id=row.rule_id,
        priority_score=row.priority_score,
    )


def _read_context(ctx: AgentContext, paths: list[str]) -> dict[str, str]:
    contents: dict[str, str] = {}
    for path in paths[:MAX_CONTEXT_FILES]:
        try:
            contents[path] = ctx.read_file(path, MAX_FILE_CONTENT_CHARS)
        except (OSError, ValueError):
            continue
    return contents


async def _run_task(
    session: AsyncSession,
    mission: Mission,
    ctx: AgentContext,
    agent: BaseAgent,
    data: Any,
    dependencies: list[str],
) -> tuple[Any, Task]:
    task = Task(
        mission_id=mission.id,
        agent_name=agent.name,
        status="running",
        dependencies=dependencies,
        input=data.model_dump() if hasattr(data, "model_dump") else dict(data),
        model=getattr(ctx.llm, "_model", ctx.llm.name),
        prompt_version=agent.prompt_version,
    )
    session.add(task)
    await session.flush()
    await log_event(session, mission.id, "started", {"agent": agent.name}, task.id)

    async def emit(event_type: str, payload: dict[str, Any]) -> None:
        await log_event(session, mission.id, event_type, payload, task.id)

    ctx.emit = emit  # per-task emitter
    started = time.monotonic()
    try:
        output, usage, attempts = await agent.run(ctx, data)
    except AgentFailure as e:
        task.status = "failed"
        task.error = str(e)[:2048]
        task.duration_ms = int((time.monotonic() - started) * 1000)
        await session.flush()
        await log_event(
            session, mission.id, "failed", {"agent": agent.name, "error": str(e)[:500]}, task.id
        )
        await session.commit()
        raise
    task.status = "completed"
    task.output = output.model_dump()
    task.token_usage = usage.model_dump()
    task.duration_ms = int((time.monotonic() - started) * 1000)
    task.attempt_count = attempts
    await session.flush()
    await session.commit()
    return output, task


async def run_mission(
    session: AsyncSession,
    mission_id: int,
    llm: LLMClient | None = None,
) -> Mission:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise MissionError("mission not found")
    repo = await session.get(Repository, mission.repo_id)
    if repo is None:
        raise MissionError("repository not found")
    analysis = await _latest_analysis(session, repo)

    transition(mission, "running")
    await log_event(session, mission.id, "mission_started", {})
    await session.commit()

    if llm is None:
        try:
            from nexus.llm.factory import get_client

            llm = get_client()
        except PermanentLLMError as e:
            mission.result = {"reason": "llm_unconfigured", "detail": str(e)}
            transition(mission, "needs_human")
            await log_event(session, mission.id, "blocked", {"reason": "llm_unconfigured"})
            await session.commit()
            await session.refresh(mission)
            return mission

    try:
        workspace = analysis_service.ensure_workspace(repo, analysis.commit_sha)
    except gitclone.CloneError as e:
        mission.result = {"reason": "workspace_unavailable", "detail": str(e)}
        transition(mission, "needs_human")
        await log_event(session, mission.id, "blocked", {"reason": "workspace_unavailable"})
        await session.commit()
        await session.refresh(mission)
        return mission

    async def _emit(event_type: str, payload: dict[str, Any]) -> None:
        await log_event(session, mission.id, event_type, payload)

    ctx = AgentContext(
        mission_id=mission.id,
        workspace=workspace,
        llm=llm,
        emit=_emit,
        max_tokens=settings.llm_max_tokens,
        timeout_s=settings.llm_timeout_s,
    )
    try:
        return await _execute_dag(session, mission, analysis, ctx)
    except AgentFailure as e:
        mission.result = {"reason": "agent_failed", "detail": str(e)[:1000]}
        transition(mission, "needs_human")
        await log_event(session, mission.id, "blocked", {"reason": "agent_failed"})
        await session.commit()
        await session.refresh(mission)
        return mission
    except Exception as e:
        mission.result = {"reason": "system_error", "detail": f"{type(e).__name__}: {e}"[:1000]}
        transition(mission, "failed")
        await log_event(session, mission.id, "failed", {"reason": "system_error"})
        await session.commit()
        await session.refresh(mission)
        return mission


async def _execute_dag(
    session: AsyncSession, mission: Mission, analysis: Analysis, ctx: AgentContext
) -> Mission:
    top_files, top_findings = await _summaries(session, analysis)
    finding = await _finding_summary(session, mission.finding_id)

    orchestrator = AGENTS["orchestrator"]
    plan_out, _ = await _run_task(
        session,
        mission,
        ctx,
        orchestrator,
        OrchestratorInput(goal=mission.goal, finding_id=mission.finding_id),
        [],
    )
    if not isinstance(plan_out, MissionPlan):
        raise MissionError("orchestrator returned invalid plan")
    mission.plan = plan_out.model_dump()
    await session.commit()

    scout_out, _ = await _run_task(
        session,
        mission,
        ctx,
        AGENTS["scout"],
        ScoutInput(
            goal=mission.goal, finding=finding, top_files=top_files, top_findings=top_findings
        ),
        ["orchestrator"],
    )
    from nexus.agents.schemas import RepoMap as RepoMapType

    if not isinstance(scout_out, RepoMapType):
        raise MissionError("scout returned invalid repo map")

    contents = _read_context(ctx, scout_out.relevant_files)
    architect_out, _ = await _run_task(
        session,
        mission,
        ctx,
        AGENTS["architect"],
        ArchitectInput(
            goal=mission.goal, finding=finding, repo_map=scout_out, file_contents=contents
        ),
        ["scout"],
    )
    from nexus.agents.schemas import ChangeProposal as ProposalType

    if not isinstance(architect_out, ProposalType):
        raise MissionError("architect returned invalid proposal")

    security_out, _ = await _run_task(
        session,
        mission,
        ctx,
        AGENTS["security"],
        SecurityInput(proposal=architect_out, file_contents=contents),
        ["architect"],
    )
    from nexus.agents.schemas import SecurityReport as SecurityType

    if not isinstance(security_out, SecurityType):
        raise MissionError("security returned invalid report")

    if security_out.verdict == "risky" or security_out.worsens_security:
        blocked = Task(
            mission_id=mission.id,
            agent_name="coder",
            status="blocked",
            dependencies=["architect", "security"],
            error="blocked by security verdict",
        )
        session.add(blocked)
        await session.flush()
        await log_event(
            session,
            mission.id,
            "blocked",
            {
                "agent": "coder",
                "reason": "security verdict: " + "; ".join(security_out.concerns[:3]),
            },
            blocked.id,
        )
        mission.result = {"reason": "security_blocked", "concerns": security_out.concerns}
        transition(mission, "needs_human")
        await session.commit()
        await session.refresh(mission)
        return mission

    coder_files = _read_context(ctx, architect_out.files_to_change or scout_out.relevant_files)
    coder_input = CoderInput(
        proposal=architect_out, security_report=security_out, file_contents=coder_files
    )
    patch_out, _ = await _run_task(
        session, mission, ctx, AGENTS["coder"], coder_input, ["architect", "security"]
    )
    from nexus.agents.schemas import PatchOutput as PatchType

    if not isinstance(patch_out, PatchType):
        raise MissionError("coder returned invalid patch")

    ok, message, files_changed = check_diff(patch_out.diff, ctx.workspace)
    if not ok:
        # One repair attempt carrying the apply error as feedback.
        await log_event(session, mission.id, "retrying", {"agent": "coder", "error": message[:500]})
        repair_input = CoderInput(
            proposal=architect_out,
            security_report=security_out,
            file_contents=coder_files,
            feedback=f"The previous diff was rejected by `git apply --check`:\n{message}\n"
            "Emit a corrected unified diff that applies cleanly.",
        )
        patch_out, _ = await _run_task(
            session, mission, ctx, AGENTS["coder"], repair_input, ["architect", "security"]
        )
        if not isinstance(patch_out, PatchType):
            raise MissionError("coder returned invalid patch")
        ok, message, files_changed = check_diff(patch_out.diff, ctx.workspace)
        if not ok:
            mission.result = {"reason": "diff_rejected", "detail": message[:1000]}
            transition(mission, "needs_human")
            await log_event(session, mission.id, "blocked", {"reason": "diff_rejected"})
            await session.commit()
            await session.refresh(mission)
            return mission

    patch = Patch(
        mission_id=mission.id,
        diff=patch_out.diff,
        files_changed=files_changed or patch_out.files_changed,
        rationale=patch_out.rationale,
        applied_state="proposed",
    )
    session.add(patch)
    await session.flush()
    mission.result = {
        "patch_id": patch.id,
        "files_changed": patch.files_changed,
        "diff_check": message,
        "proposal": architect_out.model_dump(),
        "security": security_out.model_dump(),
    }
    transition(mission, "patch_ready")
    await log_event(session, mission.id, "mission_completed", {"patch_id": patch.id})
    await session.commit()
    await session.refresh(mission)
    return mission


async def cancel_mission(session: AsyncSession, mission: Mission) -> Mission:
    transition(mission, "cancelled")
    await log_event(session, mission.id, "mission_cancelled", {})
    await session.commit()
    await session.refresh(mission)
    return mission
