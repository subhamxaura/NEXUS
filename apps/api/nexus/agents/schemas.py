"""Pydantic v2 input/output contracts for every agent. Versioned with prompts."""

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    agent: str
    depends_on: list[str] = Field(default_factory=list)


class MissionPlan(BaseModel):
    goal: str
    finding_id: int | None = None
    steps: list[PlanStep]


class FindingSummary(BaseModel):
    id: int
    type: str
    severity: str
    path: str
    line: int | None = None
    message: str
    rule_id: str
    priority_score: float


class FileSummary(BaseModel):
    path: str
    language: str
    loc: int
    complexity: float
    risk_score: float


class ScoutInput(BaseModel):
    goal: str
    finding: FindingSummary | None = None
    top_files: list[FileSummary] = Field(default_factory=list)
    top_findings: list[FindingSummary] = Field(default_factory=list)


class RepoMap(BaseModel):
    relevant_files: list[str] = Field(max_length=15)
    entry_points: list[str] = Field(default_factory=list, max_length=5)
    hotspots: list[str] = Field(default_factory=list, max_length=5)
    test_command: str | None = None
    build_system: str | None = None
    notes: str = ""


class ArchitectInput(BaseModel):
    goal: str
    finding: FindingSummary | None = None
    repo_map: RepoMap = Field(default_factory=lambda: RepoMap(relevant_files=[]))
    file_contents: dict[str, str] = Field(default_factory=dict)


class ChangeProposal(BaseModel):
    summary: str
    files_to_change: list[str] = Field(max_length=5)
    steps: list[str] = Field(max_length=8)
    impact_dependents: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    estimated_lines: int = Field(ge=0, le=500)


class SecurityInput(BaseModel):
    proposal: ChangeProposal
    file_contents: dict[str, str] = Field(default_factory=dict)


class SecurityReport(BaseModel):
    verdict: str = Field(pattern=r"^(safe|risky)$")
    concerns: list[str] = Field(default_factory=list)
    worsens_security: bool = False


class CoderInput(BaseModel):
    proposal: ChangeProposal
    security_report: SecurityReport
    file_contents: dict[str, str] = Field(default_factory=dict)
    feedback: str = ""


class PatchOutput(BaseModel):
    diff: str = Field(min_length=10)
    files_changed: list[str] = Field(min_length=1, max_length=5)
    rationale: str
    test_notes: str = ""


class TesterInput(BaseModel):
    diff: str = Field(min_length=10)
    files_changed: list[str] = Field(default_factory=list)
    test_hint: str = ""


class CommandOutcome(BaseModel):
    command: str
    exit_code: int | None = None
    status: str = Field(pattern=r"^(passed|failed|error|skipped)$")
    log_tail: str = ""
    duration_s: float = 0.0
    test_counts: dict[str, int] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    status: str = Field(pattern=r"^(passed|failed|unavailable|error)$")
    sandbox_id: str = ""
    image: str = ""
    commands: list[CommandOutcome] = Field(default_factory=list)
    test_counts: dict[str, int] = Field(default_factory=dict)
    summary: str = ""


class ReviewerInput(BaseModel):
    diff: str = Field(min_length=10)
    validation: ValidationReport
    file_contents: dict[str, str] = Field(default_factory=dict)
    proposal_summary: str = ""


class ReviewVerdict(BaseModel):
    verdict: str = Field(pattern=r"^(approve|request_changes)$")
    score: int = Field(ge=0, le=100)
    comments: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
