"""Mission orchestration: deterministic DAG, state machine, events, gates.

Phase 3 DAG: orchestrator → scout → architect → security → coder
→ tester (sandbox) → reviewer → awaiting_approval → (human) → pr_created.
Coder output must pass `git apply --check`; the Coder→Tester repair loop is
capped at two repairs; Reviewer rejection blocks the PR path. GitHub mutation
happens ONLY in services/pr.py via the human-approval endpoint.
"""

import hashlib
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
    ReviewerInput,
    ScoutInput,
    SecurityInput,
    TesterInput,
    ValidationReport,
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
    Review,
    Task,
    User,
    ValidationRun,
)
from nexus.sandbox.runner import DockerRunner, SandboxRunner
from nexus.services import analysis as analysis_service

MISSION_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "created": ("running", "cancelled"),
    "running": ("validating", "needs_human", "failed", "cancelled"),
    "validating": ("reviewing", "needs_human", "failed", "cancelled"),
    "reviewing": ("awaiting_approval", "needs_human", "failed", "cancelled"),
    "awaiting_approval": ("pr_created", "needs_human", "failed", "cancelled"),
    "pr_created": (),
    "needs_human": (),
    "failed": (),
    "cancelled": (),
}

TASK_RUN_ORDER = ("orchestrator", "scout", "architect", "security", "coder", "tester", "reviewer")
MAX_FILE_CONTENT_CHARS = 12000
MAX_CONTEXT_FILES = 6
MAX_VALIDATION_REPAIRS = 2
REVIEW_MIN_SCORE = 70


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
    sandbox: SandboxRunner | None = None,
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
        sandbox_runner=sandbox or _default_sandbox(),
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
    transition(mission, "validating")
    await session.commit()

    validation = await _validate_with_repairs(
        session, mission, ctx, patch, patch_out, architect_out, security_out, coder_files
    )
    if validation is None:
        await session.refresh(mission)
        return mission  # needs_human already recorded

    patch.applied_state = "validated"
    transition(mission, "reviewing")
    await session.commit()

    review_out, _ = await _run_task(
        session,
        mission,
        ctx,
        AGENTS["reviewer"],
        ReviewerInput(
            diff=patch.diff,
            validation=validation,
            file_contents=_read_context(ctx, patch.files_changed),
            proposal_summary=architect_out.summary,
        ),
        ["coder", "tester"],
    )
    from nexus.agents.schemas import ReviewVerdict as VerdictType

    if not isinstance(review_out, VerdictType):
        raise MissionError("reviewer returned invalid verdict")
    diff_hash = hashlib.sha256(patch.diff.encode()).hexdigest()
    session.add(
        Review(
            patch_id=patch.id,
            verdict=review_out.verdict,
            score=review_out.score,
            comments=review_out.comments,
            concerns=review_out.concerns,
            diff_hash=diff_hash,
        )
    )
    await session.flush()
    result = dict(mission.result)
    result["validation"] = validation.model_dump()
    result["review"] = {**review_out.model_dump(), "diff_hash": diff_hash}
    mission.result = result

    if review_out.verdict != "approve" or review_out.score < REVIEW_MIN_SCORE:
        mission.result = {
            **result,
            "reason": "review_rejected",
            "detail": "; ".join(review_out.concerns[:3]) or "reviewer requested changes",
        }
        transition(mission, "needs_human")
        await log_event(session, mission.id, "blocked", {"reason": "review_rejected"})
        await session.commit()
        await session.refresh(mission)
        return mission

    patch.applied_state = "reviewed"
    transition(mission, "awaiting_approval")
    await log_event(
        session, mission.id, "mission_completed", {"patch_id": patch.id, "awaiting_approval": True}
    )
    await session.commit()
    await session.refresh(mission)
    return mission


async def _validate_with_repairs(
    session: AsyncSession,
    mission: Mission,
    ctx: AgentContext,
    patch: Patch,
    patch_out: Any,
    architect_out: Any,
    security_out: Any,
    coder_files: dict[str, str],
) -> ValidationReport | None:
    """Run tester; on failure repair via coder up to MAX_VALIDATION_REPAIRS times.

    Returns the passing report, or None after recording needs_human.
    """
    from nexus.agents.schemas import PatchOutput as PatchType

    current_diff = patch_out.diff
    for attempt in range(MAX_VALIDATION_REPAIRS + 1):
        validation_out, _ = await _run_task(
            session,
            mission,
            ctx,
            AGENTS["tester"],
            TesterInput(diff=current_diff, files_changed=patch.files_changed),
            ["coder"],
        )
        if not isinstance(validation_out, ValidationReport):
            raise MissionError("tester returned invalid report")
        await _persist_validation_runs(session, patch.id, validation_out)

        if validation_out.status == "passed":
            return validation_out
        if validation_out.status == "unavailable":
            mission.result = {
                **dict(mission.result),
                "reason": "sandbox_unavailable",
                "detail": validation_out.summary[:1000],
            }
            transition(mission, "needs_human")
            await log_event(session, mission.id, "blocked", {"reason": "sandbox_unavailable"})
            await session.commit()
            return None
        if attempt >= MAX_VALIDATION_REPAIRS:
            break
        await log_event(
            session,
            mission.id,
            "retrying",
            {
                "agent": "coder",
                "repair_attempt": attempt + 1,
                "validation": validation_out.summary[:500],
            },
        )
        repair_out, _ = await _run_task(
            session,
            mission,
            ctx,
            AGENTS["coder"],
            CoderInput(
                proposal=architect_out,
                security_report=security_out,
                file_contents=coder_files,
                feedback="Sandbox validation failed:\n"
                f"{validation_out.summary}\n"
                + "\n".join(
                    f"$ {c['command']} (exit {c['exit_code']}):\n{c['log_tail'][-1500:]}"
                    for c in [cmd.model_dump() for cmd in validation_out.commands]
                )
                + "\nEmit a corrected unified diff.",
            ),
            ["architect", "security"],
        )
        if not isinstance(repair_out, PatchType):
            raise MissionError("coder returned invalid patch")
        ok, message, files_changed = check_diff(repair_out.diff, ctx.workspace)
        if not ok:
            mission.result = {
                **dict(mission.result),
                "reason": "diff_rejected",
                "detail": message[:1000],
            }
            transition(mission, "needs_human")
            await log_event(session, mission.id, "blocked", {"reason": "diff_rejected"})
            await session.commit()
            return None
        current_diff = repair_out.diff
        patch.diff = current_diff
        patch.files_changed = files_changed or repair_out.files_changed
        await session.flush()

    mission.result = {
        **dict(mission.result),
        "reason": "validation_failed",
        "detail": f"tests red after {MAX_VALIDATION_REPAIRS} repair(s)",
    }
    transition(mission, "needs_human")
    await log_event(session, mission.id, "blocked", {"reason": "validation_failed"})
    await session.commit()
    return None


async def _persist_validation_runs(
    session: AsyncSession, patch_id: int, report: ValidationReport
) -> None:
    for cmd in report.commands:
        session.add(
            ValidationRun(
                patch_id=patch_id,
                sandbox_id=report.sandbox_id,
                command=cmd.command,
                exit_code=cmd.exit_code,
                status=cmd.status,
                log_tail=cmd.log_tail[-8000:],
                test_counts=dict(cmd.test_counts),
                duration_s=cmd.duration_s,
            )
        )
    await session.flush()


async def cancel_mission(session: AsyncSession, mission: Mission) -> Mission:
    transition(mission, "cancelled")
    await log_event(session, mission.id, "mission_cancelled", {})
    await session.commit()
    await session.refresh(mission)
    return mission


def _default_sandbox() -> SandboxRunner:
    """Production default is real Docker; tests substitute a fake runner."""
    return DockerRunner()
