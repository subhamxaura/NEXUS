"""Human-approval gate + GitHub PR creation. The ONLY path to GitHub mutation.

Gates (all re-checked from persisted rows, never trusted from the caller):
1. mission.status == awaiting_approval (sole legal source transition)
2. latest sandbox validation for the patch passed
3. independent review verdict is approve with score >= threshold
4. branch is `nexus/<id>-<slug>`, never the default branch
5. a GitHub token is available (approval-time token or stored encrypted token)
"""

import shutil
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.config import settings
from nexus.core.security import decrypt_token
from nexus.github import client as gh
from nexus.models.entities import (
    Mission,
    Patch,
    PullRequest,
    Repository,
    Review,
    User,
    ValidationRun,
)
from nexus.services import missions as mission_service


def build_pr_body(
    goal: str,
    finding: dict[str, Any] | None,
    proposal: dict[str, Any],
    validation: dict[str, Any],
    review: dict[str, Any],
    files_changed: list[str],
    mission_id: int,
    commit_sha: str,
    analyzer_version: str,
) -> str:
    finding_section = (
        f"{finding.get('type')} ({finding.get('severity')}) in "
        f"`{finding.get('path')}`: {finding.get('message')}"
        if finding
        else "General goal (no single finding)."
    )
    commands = "\n".join(
        f"- `{c.get('command')}` → exit {c.get('exit_code')} ({c.get('status')})"
        for c in validation.get("commands", [])
    )
    dependents = ", ".join(f"`{d}`" for d in proposal.get("impact_dependents", []))
    risks = "; ".join(str(r) for r in proposal.get("risks", []))
    comments = "; ".join(str(c) for c in review.get("comments", []))
    return f"""## Goal
{goal}

## Finding addressed
{finding_section}

## What changed
{", ".join(f"`{f}`" for f in files_changed) or "(none)"}

## Why this approach
{proposal.get("summary", "")}

## Impact analysis
Dependents considered: {dependents or "none identified"}
Risks noted: {risks or "none noted"}

## Validation results
Status: `{validation.get("status")}` (sandbox `{validation.get("sandbox_id")}`)
Image: `{validation.get("image")}`
{commands or "(no commands recorded)"}

## Independent review verdict
`{review.get("verdict")}` — score {review.get("score")}/100
{comments or "(no comments)"}

## Known limitations
See mission trace. Validation ran in an isolated sandbox; reviewer is an AI
second opinion, not a substitute for human review.

## NEXUS mission trace
Mission #{mission_id} · analysis `{commit_sha[:12]}` · analyzer `{analyzer_version}`
"""


async def _resolve_token(mission: Mission, github_token: str | None, session: AsyncSession) -> str:
    if github_token:
        return github_token
    if mission.creator_user_id is None:
        raise mission_service.MissionError("a GitHub token is required to open a PR")
    user = await session.get(User, mission.creator_user_id)
    if user is None or not user.encrypted_token:
        raise mission_service.MissionError("a GitHub token is required to open a PR")
    try:
        return decrypt_token(user.encrypted_token)
    except RuntimeError as e:
        raise mission_service.MissionError(str(e)) from e


async def approve_mission(
    session: AsyncSession, mission_id: int, github_token: str | None = None
) -> PullRequest:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise mission_service.MissionError("mission not found")
    if mission.status != "awaiting_approval":
        raise mission_service.MissionError(
            f"mission is {mission.status}; only awaiting_approval missions can be approved"
        )
    repo = await session.get(Repository, mission.repo_id)
    if repo is None:
        raise mission_service.MissionError("repository not found")

    patch = (
        (await session.execute(select(Patch).where(Patch.mission_id == mission.id)))
        .scalars()
        .first()
    )
    review = (
        (await session.execute(select(Review).where(Review.patch_id == patch.id))).scalars().first()
        if patch
        else None
    )
    if patch is None or review is None:
        raise mission_service.MissionError("mission has no reviewed patch")
    if review.verdict != "approve" or review.score < mission_service.REVIEW_MIN_SCORE:
        raise mission_service.MissionError("review did not approve this patch")
    result = dict(mission.result)
    validation = result.get("validation")
    if not isinstance(validation, dict) or validation.get("status") != "passed":
        raise mission_service.MissionError("validation did not pass for this patch")

    token = await _resolve_token(mission, github_token, session)
    prepared: gh.PreparedBranch | None = None
    try:
        base = await gh.fetch_default_branch(repo.owner, repo.name, token)
        repo.default_branch = base
        branch = f"nexus/{mission.id}-{gh.slugify(mission.goal)}"
        message = gh.commit_message(mission.goal, mission.finding_id is not None)
        prepared = gh.push_branch(
            repo.owner,
            repo.name,
            base,
            branch,
            patch.diff,
            list(patch.files_changed),
            message,
            token,
        )
        finding = None
        if mission.finding_id is not None:
            from nexus.models.entities import Finding

            row = await session.get(Finding, mission.finding_id)
            if row is not None:
                finding = {
                    "type": row.type,
                    "severity": row.severity,
                    "path": row.path,
                    "message": row.message,
                }
        analysis_sha = ""
        analyzer_version = settings.analyzer_version
        if mission.analysis_id is not None:
            from nexus.models.entities import Analysis

            analysis = await session.get(Analysis, mission.analysis_id)
            if analysis is not None:
                analysis_sha = analysis.commit_sha
                analyzer_version = analysis.analyzer_version
        body = build_pr_body(
            mission.goal,
            finding,
            result.get("proposal", {}),
            validation,
            {"verdict": review.verdict, "score": review.score, "comments": list(review.comments)},
            list(patch.files_changed),
            mission.id,
            analysis_sha,
            analyzer_version,
        )
        title = f"NEXUS: {' '.join(mission.goal.split())[:80]}"
        created = await gh.create_pull_request(
            repo.owner, repo.name, prepared.branch, base, title, body, token
        )
    except gh.GitHubError as e:
        raise mission_service.MissionError(str(e)) from e
    finally:
        if prepared is not None:
            shutil.rmtree(prepared.workdir, ignore_errors=True)

    pr = PullRequest(
        mission_id=mission.id,
        pr_number=created.number,
        url=created.url,
        branch=branch,
        base=base,
        state="open",
    )
    session.add(pr)
    patch.applied_state = "merged_candidate"
    result["pr"] = {"number": created.number, "url": created.url, "branch": branch}
    mission.result = result
    mission_service.transition(mission, "pr_created")
    await mission_service.log_event(
        session,
        mission.id,
        "mission_pr_created",
        {"pr_number": created.number, "url": created.url, "branch": branch},
    )
    await session.commit()
    await session.refresh(pr)
    return pr


async def latest_validation(session: AsyncSession, patch_id: int) -> list[ValidationRun]:
    rows = await session.execute(
        select(ValidationRun).where(ValidationRun.patch_id == patch_id).order_by(ValidationRun.id)
    )
    return list(rows.scalars().all())
