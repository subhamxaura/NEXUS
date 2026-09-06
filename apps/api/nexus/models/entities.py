"""Phase-0 models. Full mission/patch/review tables land in Phase 2/3 migrations."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from nexus.core.database import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    login: Mapped[str] = mapped_column(String(255), index=True)
    encrypted_token: Mapped[str] = mapped_column(String(2048), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("owner", "name", name="uq_repo_owner_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_analyzed_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        UniqueConstraint("repo_id", "commit_sha", "analyzer_version", name="uq_analysis_repo_sha"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    commit_sha: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    health_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    analyzer_version: Mapped[str] = mapped_column(String(32), default="v0.1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FileMetric(Base):
    __tablename__ = "file_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), index=True)
    path: Mapped[str] = mapped_column(String(1024), index=True)
    language: Mapped[str] = mapped_column(String(32))
    loc: Mapped[int] = mapped_column(Integer, default=0)
    complexity: Mapped[float] = mapped_column(Float, default=0.0)
    maintainability: Mapped[float | None] = mapped_column(Float, nullable=True)
    churn: Mapped[int] = mapped_column(Integer, default=0)
    test_presence: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    in_degree: Mapped[int] = mapped_column(Integer, default=0)
    out_degree: Mapped[int] = mapped_column(Integer, default=0)


class DependencyEdge(Base):
    __tablename__ = "dependency_edges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), index=True)
    src_path: Mapped[str] = mapped_column(String(1024), index=True)
    dst_path: Mapped[str] = mapped_column(String(1024), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="import")


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(String(2048))
    rule_id: Mapped[str] = mapped_column(String(128))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)


class Mission(Base):
    __tablename__ = "missions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("analyses.id"), nullable=True)
    finding_id: Mapped[int | None] = mapped_column(ForeignKey("findings.id"), nullable=True)
    goal: Mapped[str] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(32), default="created", index=True)
    creator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentEvent(Base):
    """Append-only event log. No update/delete path exists by design."""

    __tablename__ = "agent_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Patch(Base):
    __tablename__ = "patches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id"), unique=True, index=True)
    diff: Mapped[str] = mapped_column(String(100000))
    files_changed: Mapped[list[str]] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(String(4096), default="")
    applied_state: Mapped[str] = mapped_column(String(32), default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ValidationRun(Base):
    __tablename__ = "validation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patch_id: Mapped[int] = mapped_column(ForeignKey("patches.id"), index=True)
    sandbox_id: Mapped[str] = mapped_column(String(128), default="")
    command: Mapped[str] = mapped_column(String(1024))
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="passed")
    log_tail: Mapped[str] = mapped_column(String(20000), default="")
    test_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patch_id: Mapped[int] = mapped_column(ForeignKey("patches.id"), unique=True, index=True)
    verdict: Mapped[str] = mapped_column(String(32))
    score: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[list[str]] = mapped_column(JSON, default=list)
    concerns: Mapped[list[str]] = mapped_column(JSON, default=list)
    diff_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PullRequest(Base):
    __tablename__ = "pull_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id"), unique=True, index=True)
    pr_number: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str] = mapped_column(String(1024), default="")
    branch: Mapped[str] = mapped_column(String(255), default="")
    base: Mapped[str] = mapped_column(String(255), default="main")
    state: Mapped[str] = mapped_column(String(32), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
