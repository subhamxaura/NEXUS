"""Workspace prep + test-command detection for sandbox validation."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def copy_snapshot(snapshot: Path, dest: Path) -> None:
    """Copy working-tree files (excluding .git) into the sandbox workspace."""
    for entry in snapshot.iterdir():
        if entry.name == ".git":
            continue
        target = dest / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, ignore_dangling_symlinks=True)
        else:
            shutil.copy2(entry, target)


def apply_diff_to_copy(diff: str, snapshot: Path, workspace: Path) -> tuple[bool, str]:
    """Copy snapshot, apply diff with LF-safe handling. Returns (ok, message)."""
    copy_snapshot(snapshot, workspace)
    normalized = diff.replace("\r\n", "\n").replace("\r", "\n")
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False, newline="") as tmp:
        tmp.write(normalized)
        tmp_path = tmp.name
    try:
        proc = subprocess.run(  # noqa: S603, S607 -- fixed git binary, no shell
            ["git", "-c", "core.autocrlf=false", "apply", tmp_path],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(workspace),
        )
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"could not apply diff: {e}"
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        err = ((proc.stderr or "") + (proc.stdout or "")).strip()[:2000]
        return False, err or "diff does not apply"
    return True, "diff applied"


def _has_pytest_signals(workspace: Path) -> bool:
    if (workspace / "pytest.ini").exists() or (workspace / "tox.ini").exists():
        return True
    pyproject = workspace / "pyproject.toml"
    if pyproject.exists() and "[tool.pytest" in pyproject.read_text(errors="replace"):
        return True
    for path in workspace.rglob("test_*.py"):
        if ".git" not in path.parts:
            return True
    return False


def detect_commands(workspace: Path) -> list[tuple[str, str]]:
    """Detect (image_key, command) pairs. Empty when nothing reliable exists."""
    commands: list[tuple[str, str]] = []
    if _has_pytest_signals(workspace):
        commands.append(("python", "python -m pytest -q"))
    package_json = workspace / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text())
            scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError, AttributeError):
            scripts = {}
        test_script = str(scripts.get("test", "")) if isinstance(scripts, dict) else ""
        # Skip placeholder scripts like `echo "no tests"`.
        if test_script and "echo" not in test_script:
            commands.append(("node", "npm test"))
    return commands
