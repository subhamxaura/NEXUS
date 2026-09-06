"""Recent churn from git history: commit count per file over the clone depth."""

import subprocess
from pathlib import Path


def file_churn(repo_dir: Path, rel_path: str) -> int:
    """Number of commits touching `rel_path`. 0 when history is unavailable."""
    try:
        proc = subprocess.run(  # noqa: S603, S607 -- fixed git binary, no shell
            ["git", "-C", str(repo_dir), "log", "--format=%H", "--", rel_path],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return 0
    if proc.returncode != 0:
        return 0
    return sum(1 for line in proc.stdout.splitlines() if line.strip())


def batch_churn(repo_dir: Path, rel_paths: list[str]) -> dict[str, int]:
    return {p: file_churn(repo_dir, p) for p in rel_paths}
