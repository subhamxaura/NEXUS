"""Recent churn from git history: commit count per file over the clone depth."""

import subprocess
from pathlib import Path

# Path args per git invocation. ~500 * 100B stays far below the ~32KiB
# Windows CreateProcess limit while keeping batches large enough to matter.
_BATCH_SIZE = 500


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


def _parse_name_only_log(stdout: str) -> dict[str, int]:
    """Per-path commit counts from `git log --name-only` output.

    Lines are either a commit header, the blank separator, or file paths in
    the commit body. Anything unparseable (history rewrite, exotic encodings)
    yields fewer counts — never a crash.
    """
    counts: dict[str, int] = {}
    in_body = False
    for line in stdout.splitlines():
        if line.startswith("commit "):
            in_body = False
        elif not line.strip():
            in_body = True
        elif in_body:
            path = line.strip()
            counts[path] = counts.get(path, 0) + 1
    return counts


def _git_churn_counts(repo_dir: Path, rel_paths: list[str]) -> dict[str, int] | None:
    """One batched pass: per-path commit counts. None when git fails."""
    counts: dict[str, int] = {}
    # Dedupe (order-preserving): a path listed twice — or spanning two
    # batches — must be counted once, matching per-file `file_churn`.
    unique_paths = list(dict.fromkeys(rel_paths))
    for start in range(0, len(unique_paths), _BATCH_SIZE):
        batch = unique_paths[start : start + _BATCH_SIZE]
        try:
            proc = subprocess.run(  # noqa: S603 -- fixed git binary, no shell
                [  # noqa: S607 -- fixed git binary, no shell
                    "git",
                    "-C",
                    str(repo_dir),
                    "log",
                    # Literal "commit " prefix: unambiguous header marker even
                    # if a file path itself starts with "commit ".
                    "--format=commit %H",
                    "--name-only",
                    # Pre-fix semantics: a rename is an add on the new path,
                    # not a touch of the old one.
                    "--no-renames",
                    "--",
                    *batch,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        if proc.returncode != 0:
            return None
        for path, n in _parse_name_only_log(proc.stdout).items():
            counts[path] = counts.get(path, 0) + n
    return counts


def batch_churn(repo_dir: Path, rel_paths: list[str]) -> dict[str, int]:
    """Commit count per path via one batched `git log` per ~500-path batch.

    Semantics unchanged from the per-file implementation: count of commits
    touching each path, 0 when history is unavailable, and paths missing from
    history map to 0. Falls back to per-file queries when git fails.
    """
    if not rel_paths:
        return {}
    counts = _git_churn_counts(repo_dir, rel_paths)
    if counts is None:
        return {p: file_churn(repo_dir, p) for p in rel_paths}
    return {p: counts.get(p, 0) for p in rel_paths}
