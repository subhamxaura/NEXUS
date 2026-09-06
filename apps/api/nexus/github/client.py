"""GitHub mutation layer: branch/commit/push via git CLI + PR via REST.

Used ONLY from the human-approval endpoint after validation + review gates.
Tokens live in memory for the call duration; captured subprocess/HTTP output
is scrubbed of the token before it can reach logs, events, or errors.
"""

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

API_BASE = "https://api.github.com"
BOT_AUTHOR = "NEXUS <bot@nexus>"


class GitHubError(RuntimeError):
    pass


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "[REDACTED]") if token else text


def _run_git(args: list[str], cwd: Path, token: str, timeout_s: int = 180) -> str:
    import os

    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        proc = subprocess.run(  # noqa: S603, S607 -- fixed git binary, no shell
            ["git"] + args,  # noqa: S607 -- git binary from PATH
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(cwd),
            env=env,
        )
    except (subprocess.SubprocessError, OSError) as e:
        raise GitHubError(f"git {' '.join(args[:2])} failed: {e}") from e
    if proc.returncode != 0:
        err = _scrub(((proc.stderr or "") + (proc.stdout or "")).strip()[:1000], token)
        raise GitHubError(f"git {' '.join(args[:2])} failed: {err or 'unknown error'}")
    return _scrub(proc.stdout.strip(), token)


@dataclass(frozen=True)
class PreparedBranch:
    workdir: Path
    branch: str
    base: str
    commit_sha: str


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug or "change")[:limit]


def commit_message(goal: str, has_finding: bool) -> str:
    prefix = "fix" if has_finding else "chore"
    short = " ".join(goal.split())[:72] or "update code"
    return f"{prefix}(nexus): {short}\n\nCo-authored-by: {BOT_AUTHOR}"


def push_branch(
    owner: str,
    name: str,
    base: str,
    branch: str,
    diff: str,
    files_changed: list[str],
    message: str,
    token: str,
) -> PreparedBranch:
    """Clone, branch off `base`, apply the diff, commit, push. No merging, ever."""
    if branch == base or not branch.startswith("nexus/"):
        raise GitHubError("refusing to work on a non-nexus branch")
    workdir = Path(tempfile.mkdtemp(prefix="nexus-pr-"))
    try:
        clone_url = f"https://x-access-token:{token}@github.com/{owner}/{name}.git"
        _run_git(["clone", "--depth", "50", clone_url, "."], workdir, token)
        _run_git(["checkout", "-b", branch, f"origin/{base}"], workdir, token)
        normalized = diff.replace("\r\n", "\n").replace("\r", "\n")
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False, newline="") as tmp:
            tmp.write(normalized)
            diff_path = tmp.name
        try:
            _run_git(["apply", "--index", diff_path], workdir, token)
        finally:
            Path(diff_path).unlink(missing_ok=True)
        _run_git(["add", "--", *files_changed], workdir, token)
        _run_git(
            ["-c", "user.name=NEXUS", "-c", "user.email=bot@nexus", "commit", "-m", message],
            workdir,
            token,
        )
        commit_sha = _run_git(["rev-parse", "HEAD"], workdir, token)
        _run_git(["push", "origin", branch], workdir, token)
    except BaseException:
        import shutil

        shutil.rmtree(workdir, ignore_errors=True)
        raise
    return PreparedBranch(workdir=workdir, branch=branch, base=base, commit_sha=commit_sha)


@dataclass(frozen=True)
class CreatedPR:
    number: int
    url: str


async def create_pull_request(
    owner: str,
    name: str,
    head: str,
    base: str,
    title: str,
    body: str,
    token: str,
    timeout_s: int = 30,
) -> CreatedPR:
    if head == base:
        raise GitHubError("refusing to open a PR against its own head")
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(
                f"{API_BASE}/repos/{owner}/{name}/pulls",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"title": title, "head": head, "base": base, "body": body},
            )
    except httpx.HTTPError as e:
        raise GitHubError("GitHub API unreachable") from e
    if resp.status_code not in (200, 201):
        raise GitHubError(f"PR creation failed (HTTP {resp.status_code})")
    try:
        data = resp.json()
        return CreatedPR(number=int(data["number"]), url=str(data["html_url"]))
    except (ValueError, KeyError, TypeError) as e:
        raise GitHubError("GitHub returned an unexpected PR payload") from e


async def fetch_default_branch(owner: str, name: str, token: str, timeout_s: int = 30) -> str:
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(
                f"{API_BASE}/repos/{owner}/{name}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
    except httpx.HTTPError as e:
        raise GitHubError("GitHub API unreachable") from e
    if resp.status_code != 200:
        raise GitHubError(f"could not read repository (HTTP {resp.status_code})")
    try:
        return str(resp.json().get("default_branch") or "main")
    except (ValueError, AttributeError) as e:
        raise GitHubError("GitHub returned an unexpected repository payload") from e
