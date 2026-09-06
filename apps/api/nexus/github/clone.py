"""Shallow, isolated git clones for analysis. Public repos only in Phase 1."""

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_OWNER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-\.]*$")
_URL_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-\.]+?)(?:\.git)?/?$")


class CloneError(RuntimeError):
    pass


@dataclass(frozen=True)
class CloneResult:
    workdir: Path
    sha: str


def validate_repo_url(url: str) -> tuple[str, str]:
    """Return (owner, name) or raise CloneError. Only public github.com HTTPS."""
    match = _URL_RE.match(url.strip())
    if not match:
        raise CloneError("only public https://github.com/<owner>/<repo> URLs are supported")
    return match.group(1), match.group(2)


def validate_owner_name(owner: str, name: str) -> None:
    if not _OWNER_RE.match(owner) or not _NAME_RE.match(name) or ".." in name:
        raise CloneError("invalid owner or repository name")


def repo_url(owner: str, name: str) -> str:
    validate_owner_name(owner, name)
    return f"https://github.com/{owner}/{name}.git"


def clone(url: str, timeout_s: int = 180) -> CloneResult:
    validate_repo_url(url)
    workdir = Path(tempfile.mkdtemp(prefix="nexus-clone-"))
    try:
        proc = subprocess.run(  # noqa: S603, S607 -- fixed git binary, validated args, no shell
            ["git", "clone", "--depth", "50", url, str(workdir)],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (subprocess.SubprocessError, OSError) as e:
        shutil.rmtree(workdir, ignore_errors=True)
        raise CloneError(f"clone failed: {e}") from e
    if proc.returncode != 0:
        shutil.rmtree(workdir, ignore_errors=True)
        raise CloneError("clone failed: repository not found or not public")
    sha = head_sha(workdir)
    return CloneResult(workdir=workdir, sha=sha)


def head_sha(workdir: Path) -> str:
    try:
        proc = subprocess.run(  # noqa: S603, S607 -- fixed git binary, no shell
            ["git", "-C", str(workdir), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as e:
        raise CloneError(f"could not resolve HEAD sha: {e}") from e
    if proc.returncode != 0:
        raise CloneError("could not resolve HEAD sha")
    return proc.stdout.strip()


def dispose(workdir: Path) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
