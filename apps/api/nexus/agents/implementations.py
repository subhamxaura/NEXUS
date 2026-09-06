"""Concrete agents: deterministic Orchestrator + LLM Scout/Architect/Security/Coder."""

from pydantic import BaseModel, ValidationError

from nexus.agents.base import AgentFailure, BaseAgent
from nexus.agents.context import AgentContext
from nexus.agents.schemas import (
    ArchitectInput,
    ChangeProposal,
    CoderInput,
    CommandOutcome,
    MissionPlan,
    PatchOutput,
    PlanStep,
    RepoMap,
    ReviewerInput,
    ReviewVerdict,
    ScoutInput,
    SecurityInput,
    SecurityReport,
    TesterInput,
    ValidationReport,
)
from nexus.llm.client import TokenUsage


class OrchestratorInput(BaseModel):
    goal: str
    finding_id: int | None = None


class OrchestratorAgent(BaseAgent):
    """Builds the bounded mission DAG deterministically (no LLM needed)."""

    name = "orchestrator"
    input_schema = OrchestratorInput
    output_schema = MissionPlan
    prompt_version = "deterministic-v1"

    async def run(self, ctx: AgentContext, data: BaseModel) -> tuple[BaseModel, TokenUsage, int]:
        validated = self.input_schema.model_validate(data.model_dump())
        if not isinstance(validated, OrchestratorInput):
            raise AgentFailure("orchestrator received invalid input")
        plan = self.build_plan(goal=validated.goal, finding_id=validated.finding_id)
        await ctx.emit("completed", {"agent": self.name, "steps": len(plan.steps)})
        return plan, TokenUsage(), 1

    @staticmethod
    def build_plan(goal: str, finding_id: int | None) -> MissionPlan:
        return MissionPlan(
            goal=goal,
            finding_id=finding_id,
            steps=[
                PlanStep(agent="scout", depends_on=[]),
                PlanStep(agent="architect", depends_on=["scout"]),
                PlanStep(agent="security", depends_on=["architect"]),
                PlanStep(agent="coder", depends_on=["architect", "security"]),
                PlanStep(agent="tester", depends_on=["coder"]),
                PlanStep(agent="reviewer", depends_on=["coder", "tester"]),
            ],
        )


class ScoutAgent(BaseAgent):
    name = "scout"
    input_schema = ScoutInput
    output_schema = RepoMap
    prompt_file = "scout_v1.md"
    prompt_version = "scout_v1"


class ArchitectAgent(BaseAgent):
    name = "architect"
    input_schema = ArchitectInput
    output_schema = ChangeProposal
    prompt_file = "architect_v1.md"
    prompt_version = "architect_v1"


class SecurityAgent(BaseAgent):
    name = "security"
    input_schema = SecurityInput
    output_schema = SecurityReport
    prompt_file = "security_v1.md"
    prompt_version = "security_v1"


class CoderAgent(BaseAgent):
    name = "coder"
    input_schema = CoderInput
    output_schema = PatchOutput
    prompt_file = "coder_v1.md"
    prompt_version = "coder_v1"


class TesterAgent(BaseAgent):
    """Runs the patch in the sandbox deterministically (no LLM: facts only)."""

    name = "tester"
    input_schema = TesterInput
    output_schema = ValidationReport
    prompt_version = "deterministic-v1"

    async def run(self, ctx: AgentContext, data: BaseModel) -> tuple[BaseModel, TokenUsage, int]:
        validated = self.input_schema.model_validate(data.model_dump())
        if not isinstance(validated, TesterInput):
            raise AgentFailure("tester received invalid input")
        if ctx.sandbox_runner is None:
            raise AgentFailure("no sandbox runner configured")
        await ctx.emit("started", {"agent": self.name})
        await ctx.emit("progress", {"agent": self.name, "stage": "applying diff in sandbox"})
        result = ctx.sandbox_runner.validate(validated.diff, ctx.workspace, [])
        await ctx.emit("progress", {"agent": self.name, "stage": "collecting results"})
        try:
            report = ValidationReport(
                status=result.status,
                sandbox_id=result.sandbox_id,
                image=result.image,
                commands=[
                    CommandOutcome(
                        command=c.command,
                        exit_code=c.exit_code,
                        status=c.status,
                        log_tail=c.log_tail,
                        duration_s=c.duration_s,
                        test_counts=dict(c.test_counts),
                    )
                    for c in result.commands
                ],
                test_counts={
                    key: sum(c.test_counts.get(key, 0) for c in result.commands)
                    for key in {k for c in result.commands for k in c.test_counts}
                },
                summary=result.summary,
            )
        except ValidationError as e:
            raise AgentFailure(f"tester produced invalid report: {e}") from e
        await ctx.emit("completed", {"agent": self.name, "status": report.status})
        return report, TokenUsage(), 1


class ReviewerAgent(BaseAgent):
    name = "reviewer"
    input_schema = ReviewerInput
    output_schema = ReviewVerdict
    prompt_file = "reviewer_v1.md"
    prompt_version = "reviewer_v1"


AGENTS: dict[str, BaseAgent] = {
    "orchestrator": OrchestratorAgent(),
    "scout": ScoutAgent(),
    "architect": ArchitectAgent(),
    "security": SecurityAgent(),
    "coder": CoderAgent(),
    "tester": TesterAgent(),
    "reviewer": ReviewerAgent(),
}
