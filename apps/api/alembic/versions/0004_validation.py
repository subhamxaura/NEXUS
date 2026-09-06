"""Phase 3: validation_runs, reviews, pull_requests."""

import sqlalchemy as sa

from alembic import op

revision = "0004_validation"
down_revision = "0003_missions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "validation_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("patch_id", sa.Integer, sa.ForeignKey("patches.id"), nullable=False, index=True),
        sa.Column("sandbox_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("command", sa.String(1024), nullable=False),
        sa.Column("exit_code", sa.Integer, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="passed"),
        sa.Column("log_tail", sa.String(20000), nullable=False, server_default=""),
        sa.Column("test_counts", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("duration_s", sa.Float, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "patch_id",
            sa.Integer,
            sa.ForeignKey("patches.id"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("comments", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("concerns", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("diff_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "pull_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "mission_id",
            sa.Integer,
            sa.ForeignKey("missions.id"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("pr_number", sa.Integer, nullable=False, server_default="0"),
        sa.Column("url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("branch", sa.String(255), nullable=False, server_default=""),
        sa.Column("base", sa.String(255), nullable=False, server_default="main"),
        sa.Column("state", sa.String(32), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("pull_requests")
    op.drop_table("reviews")
    op.drop_table("validation_runs")
