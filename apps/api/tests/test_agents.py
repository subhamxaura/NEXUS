"""Agent contract tests with the scripted fake LLM (no network)."""

from pathlib import Path
from typing import Any

import pytest

from nexus.agents.base import AgentFailure
from nexus.agents.context import AgentContext
from nexus.agents.implementations import AGENTS, OrchestratorInput
from nexus.agents.schemas import (
    ArchitectInput,
    ChangeProposal,
    CoderInput,
    RepoMap,
    ReviewerInput,
    ScoutInput,
    SecurityInput,
    SecurityReport,
    TesterInput,
)
from nexus.llm.client import LLMResult, TokenUsage, TransientLLMError
from nexus.llm.fake import FakeLLMClient

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"

SCOUT_OUT = {
    "relevant_files": ["helpers.py", "risky.py"],
    "entry_points": ["helpers.py"],
    "hotspots": ["risky.py"],
    "test_command": None,
    "build_system": None,
    "notes": "tiny fixture",
}
ARCHITECT_OUT = {
    "summary": "Append punctuation in greet",
    "files_to_change": ["helpers.py"],
    "steps": ["edit return line in greet"],
    "impact_dependents": [],
    "risks": [],
    "estimated_lines": 2,
}
SECURITY_OUT = {"verdict": "safe", "concerns": [], "worsens_security": False}
CODER_OUT = {
    "diff": "--- a/helpers.py\n+++ b/helpers.py\n@@ -5,7 +5,7 @@\n"
    ' def greet(name):\n     if not name:\n         return "hello"\n'
    '-    return f"hello {name} {tiny()}"\n'
    '+    return f"hello {name} {tiny()}!".strip()\n \n \n print(greet("world"))\n',
    "files_changed": ["helpers.py"],
    "rationale": "Minimal one-line change per the proposal.",
    "test_notes": "python helpers.py",
}


def make_ctx(fake: FakeLLMClient) -> tuple[AgentContext, list[tuple[str, dict[str, Any]]]]:
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    return AgentContext(mission_id=1, workspace=FIXTURE, llm=fake, emit=emit), events


async def test_scout_architect_security_coder_happy_path() -> None:
    fake = FakeLLMClient(
        {
            "scout": [SCOUT_OUT],
            "architect": [ARCHITECT_OUT],
            "security": [SECURITY_OUT],
            "coder": [CODER_OUT],
        }
    )
    ctx, _ = make_ctx(fake)

    scout_out, usage, attempts = await AGENTS["scout"].run(
        ctx, ScoutInput(goal="fix greet", top_files=[], top_findings=[])
    )
    assert isinstance(scout_out, RepoMap)
    assert scout_out.relevant_files == ["helpers.py", "risky.py"]
    assert attempts == 1 and usage.model == "fake-test"

    arch_out, _, _ = await AGENTS["architect"].run(
        ctx, ArchitectInput(goal="fix greet", repo_map=scout_out, file_contents={})
    )
    assert isinstance(arch_out, ChangeProposal)

    sec_out, _, _ = await AGENTS["security"].run(
        ctx, SecurityInput(proposal=arch_out, file_contents={})
    )
    assert isinstance(sec_out, SecurityReport)
    assert sec_out.verdict == "safe"

    coder_out, _, _ = await AGENTS["coder"].run(
        ctx, CoderInput(proposal=arch_out, security_report=sec_out, file_contents={})
    )
    assert coder_out.files_changed == ["helpers.py"]  # type: ignore[attr-defined]


async def test_schema_failure_reprompts_once_then_succeeds() -> None:
    bad = {"files_changed": ["helpers.py"], "rationale": "x"}  # missing diff
    fake = FakeLLMClient({"coder": [bad, CODER_OUT]})
    ctx, events = make_ctx(fake)
    agent = AGENTS["coder"]
    out, _, attempts = await agent.run(
        ctx,
        CoderInput(
            proposal=ChangeProposal(
                summary="s", files_to_change=["helpers.py"], steps=["x"], estimated_lines=1
            ),
            security_report=SecurityReport(verdict="safe"),
            file_contents={},
        ),
    )
    assert attempts == 2
    assert out is not None
    assert any(e[0] == "retrying" for e in events)


async def test_persistent_schema_failure_raises() -> None:
    fake = FakeLLMClient({"coder": [{"nope": 1}, {"nope": 2}, {"nope": 3}, {"nope": 4}]})
    ctx, _ = make_ctx(fake)
    with pytest.raises(AgentFailure):
        await AGENTS["coder"].run(
            ctx,
            CoderInput(
                proposal=ChangeProposal(
                    summary="s", files_to_change=["h"], steps=["x"], estimated_lines=1
                ),
                security_report=SecurityReport(verdict="safe"),
                file_contents={},
            ),
        )
    assert len(fake.calls) == 3


async def test_transient_errors_retry_with_backoff() -> None:
    class Flaky(FakeLLMClient):
        def __init__(self) -> None:
            super().__init__({})
            self.n = 0

        async def complete_json(self, messages, response_model, max_tokens=4000, timeout_s=120):  # type: ignore[override]
            self.n += 1
            if self.n < 3:
                raise TransientLLMError("rate limited")
            return LLMResult(data=SCOUT_OUT, usage=TokenUsage(model="flaky"))

    ctx, _ = make_ctx(Flaky())
    out, _, attempts = await AGENTS["scout"].run(ctx, ScoutInput(goal="g"))
    assert attempts == 3
    assert isinstance(out, RepoMap)


async def test_orchestrator_deterministic_no_llm() -> None:
    fake = FakeLLMClient({})
    ctx, events = make_ctx(fake)
    out, usage, attempts = await AGENTS["orchestrator"].run(
        ctx, OrchestratorInput(goal="fix it", finding_id=7)
    )
    assert attempts == 1 and usage.prompt_tokens == 0 and fake.calls == []
    assert [s.agent for s in out.steps] == [  # type: ignore[attr-defined]
        "scout",
        "architect",
        "security",
        "coder",
        "tester",
        "reviewer",
    ]
    deps = {s.agent: s.depends_on for s in out.steps}  # type: ignore[attr-defined]
    assert deps == {
        "scout": [],
        "architect": ["scout"],
        "security": ["architect"],
        "coder": ["architect", "security"],
        "tester": ["coder"],
        "reviewer": ["coder", "tester"],
    }
    assert events[0][0] == "completed"


async def test_prompts_versioned_and_present() -> None:
    for agent in AGENTS.values():
        if agent.prompt_file:
            path = Path("nexus/agents/prompts") / agent.prompt_file
            assert path.exists(), f"missing prompt {agent.prompt_file}"
            assert agent.prompt_version in agent.prompt_file
    assert set(AGENTS) == {
        "orchestrator",
        "scout",
        "architect",
        "security",
        "coder",
        "tester",
        "reviewer",
    }


async def test_tester_reports_sandbox_facts_deterministically() -> None:
    from nexus.sandbox.runner import CommandResult, FakeRunner, SandboxResult

    passed = SandboxResult(
        status="passed",
        sandbox_id="fake-1",
        image="python",
        commands=(
            CommandResult(
                command="python -m pytest -q",
                exit_code=0,
                status="passed",
                log_tail="1 passed",
                duration_s=1.2,
                test_counts={"passed": 1},
            ),
        ),
        summary="all passed",
    )
    ctx, _ = make_ctx(FakeLLMClient({}))
    ctx.sandbox_runner = FakeRunner(passed)
    out, usage, attempts = await AGENTS["tester"].run(
        ctx, TesterInput(diff=CODER_OUT["diff"], files_changed=["helpers.py"])
    )  # type: ignore[arg-type]
    assert attempts == 1 and usage.prompt_tokens == 0  # no LLM involved
    assert out.status == "passed"  # type: ignore[attr-defined]
    assert out.test_counts == {"passed": 1}  # type: ignore[attr-defined]


async def test_tester_surfaces_unavailable_honestly() -> None:
    from nexus.sandbox.runner import FakeRunner, SandboxResult

    unavailable = SandboxResult(
        status="unavailable", sandbox_id="unavailable", image="", commands=(), summary="no docker"
    )
    ctx, _ = make_ctx(FakeLLMClient({}))
    ctx.sandbox_runner = FakeRunner(unavailable)
    out, _, _ = await AGENTS["tester"].run(ctx, TesterInput(diff=CODER_OUT["diff"]))  # type: ignore[arg-type]
    assert out.status == "unavailable"  # type: ignore[attr-defined]


async def test_reviewer_judges_independently() -> None:
    from nexus.agents.schemas import ValidationReport

    fake = FakeLLMClient(
        {
            "reviewer": [
                {
                    "verdict": "request_changes",
                    "score": 40,
                    "comments": ["validation unavailable"],
                    "concerns": ["no test evidence"],
                }
            ]
        }
    )
    ctx, _ = make_ctx(fake)
    out, _, _ = await AGENTS["reviewer"].run(
        ctx,
        ReviewerInput(
            diff=CODER_OUT["diff"],  # type: ignore[arg-type]
            validation=ValidationReport(status="unavailable", summary="no docker"),
            file_contents={},
            proposal_summary="one-liner",
        ),
    )
    assert out.verdict == "request_changes"  # type: ignore[attr-defined]
