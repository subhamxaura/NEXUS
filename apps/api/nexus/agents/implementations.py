"""Concrete agents: deterministic Orchestrator + LLM Scout/Architect/Security/Coder."""

from pydantic import BaseModel

from nexus.agents.base import AgentFailure, BaseAgent
from nexus.agents.context import AgentContext
from nexus.agents.schemas import (
    ArchitectInput,
    ChangeProposal,
    CoderInput,
    MissionPlan,
    PatchOutput,
    PlanStep,
    RepoMap,
    ScoutInput,
    SecurityInput,
    SecurityReport,
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


AGENTS: dict[str, BaseAgent] = {
    "orchestrator": OrchestratorAgent(),
    "scout": ScoutAgent(),
    "architect": ArchitectAgent(),
    "security": SecurityAgent(),
    "coder": CoderAgent(),
}
