"""Phase 1: analyses, file_metrics, dependency_edges, findings."""

import sqlalchemy as sa

from alembic import op

revision = "0002_intel"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analyses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "repo_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False, index=True
        ),
        sa.Column("commit_sha", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending", index=True),
        sa.Column("health_score", sa.Float, nullable=True),
        sa.Column("metrics", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("analyzer_version", sa.String(32), nullable=False, server_default="v0.1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "repo_id", "commit_sha", "analyzer_version", name="uq_analysis_repo_sha"
        ),
    )
    op.create_table(
        "file_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "analysis_id", sa.Integer, sa.ForeignKey("analyses.id"), nullable=False, index=True
        ),
        sa.Column("path", sa.String(1024), nullable=False, index=True),
        sa.Column("language", sa.String(32), nullable=False),
        sa.Column("loc", sa.Integer, nullable=False, server_default="0"),
        sa.Column("complexity", sa.Float, nullable=False, server_default="0"),
        sa.Column("maintainability", sa.Float, nullable=True),
        sa.Column("churn", sa.Integer, nullable=False, server_default="0"),
        sa.Column("test_presence", sa.Float, nullable=False, server_default="0"),
        sa.Column("risk_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("in_degree", sa.Integer, nullable=False, server_default="0"),
        sa.Column("out_degree", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "dependency_edges",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "analysis_id", sa.Integer, sa.ForeignKey("analyses.id"), nullable=False, index=True
        ),
        sa.Column("src_path", sa.String(1024), nullable=False, index=True),
        sa.Column("dst_path", sa.String(1024), nullable=False, index=True),
        sa.Column("kind", sa.String(32), nullable=False, server_default="import"),
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "analysis_id", sa.Integer, sa.ForeignKey("analyses.id"), nullable=False, index=True
        ),
        sa.Column("type", sa.String(64), nullable=False, index=True),
        sa.Column("severity", sa.String(16), nullable=False, index=True),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("line", sa.Integer, nullable=True),
        sa.Column("message", sa.String(2048), nullable=False),
        sa.Column("rule_id", sa.String(128), nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("priority_score", sa.Float, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("findings")
    op.drop_table("dependency_edges")
    op.drop_table("file_metrics")
    op.drop_table("analyses")
