"""Phase 2: missions, tasks, agent_events (append-only), patches."""

import sqlalchemy as sa

from alembic import op

revision = "0003_missions"
down_revision = "0002_intel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "missions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "repo_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False, index=True
        ),
        sa.Column("analysis_id", sa.Integer, sa.ForeignKey("analyses.id"), nullable=True),
        sa.Column("finding_id", sa.Integer, sa.ForeignKey("findings.id"), nullable=True),
        sa.Column("goal", sa.String(2048), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="created", index=True),
        sa.Column("creator_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("plan", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("result", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "mission_id", sa.Integer, sa.ForeignKey("missions.id"), nullable=False, index=True
        ),
        sa.Column("agent_name", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending", index=True),
        sa.Column("dependencies", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("input", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("output", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("token_usage", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("prompt_version", sa.String(32), nullable=False, server_default=""),
        sa.Column("error", sa.String(2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "agent_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "mission_id", sa.Integer, sa.ForeignKey("missions.id"), nullable=False, index=True
        ),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("tasks.id"), nullable=True, index=True),
        sa.Column("event_type", sa.String(32), nullable=False, index=True),
        sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "patches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "mission_id",
            sa.Integer,
            sa.ForeignKey("missions.id"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("diff", sa.String(100000), nullable=False),
        sa.Column("files_changed", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("rationale", sa.String(4096), nullable=False, server_default=""),
        sa.Column("applied_state", sa.String(32), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("patches")
    op.drop_table("agent_events")
    op.drop_table("tasks")
    op.drop_table("missions")
