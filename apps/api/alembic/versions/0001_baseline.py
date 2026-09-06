"""Baseline: users + repositories."""

import sqlalchemy as sa

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("github_id", sa.Integer, nullable=False, unique=True, index=True),
        sa.Column("login", sa.String(255), nullable=False, index=True),
        sa.Column("encrypted_token", sa.String(2048), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner", sa.String(255), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False, index=True),
        sa.Column("default_branch", sa.String(255), server_default="main"),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("last_analyzed_sha", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("owner", "name", name="uq_repo_owner_name"),
    )


def downgrade() -> None:
    op.drop_table("repositories")
    op.drop_table("users")
