"""Sandbox execution: Docker with strict isolation; truthful unavailable without it.

Isolation baseline (spec): --network none for test execution, 2g RAM, 2 CPUs,
read-only root fs, tmpfs scratch, 10-minute max. Dependency install runs in a
separate ephemeral container WITH network, and only from lockfiles
(requirements.txt / package-lock.json) — test execution itself is always
offline. Every deviation from this is recorded in the result, never silent.
"""

import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

PYTHON_IMAGE = "python:3.11-slim"
NODE_IMAGE = "node:20-slim"
MEMORY = "2g"
CPUS = "2"
INSTALL_TIMEOUT_S = 300
TEST_TIMEOUT_S = 600
LOG_TAIL_CHARS = 8000


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int | None
    status: str  # passed | failed | error | skipped
    log_tail: str
    duration_s: float
    test_counts: dict[str, int]


@dataclass(frozen=True)
class SandboxResult:
    status: str  # passed | failed | unavailable | error
    sandbox_id: str
    image: str
    commands: tuple[CommandResult, ...]
    summary: str


class SandboxRunner(Protocol):
    name: str

    def available(self) -> bool: ...

    def validate(
        self,
        diff: str,
        snapshot: Path,
        commands: list[tuple[str, str]],
        timeout_s: int = TEST_TIMEOUT_S,
    ) -> SandboxResult:
        """Apply `diff` to a copy of `snapshot`, run (image, command) pairs."""
        ...


def docker_available(timeout_s: int = 10) -> bool:
    try:
        proc = subprocess.run(  # noqa: S603, S607 -- fixed docker binary, no shell
            ["docker", "info", "--format", "{{.ServerVersion}}"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return proc.returncode == 0


def _tail(text: str, limit: int = LOG_TAIL_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"[... truncated {len(text) - limit} chars ...]\n" + text[-limit:]


def _coerce_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class DockerRunner:
    """Real Docker sandbox. Requires a Docker daemon; else reports unavailable."""

    name = "docker"

    def __init__(
        self,
        memory: str = MEMORY,
        cpus: str = CPUS,
        install_timeout_s: int = INSTALL_TIMEOUT_S,
        test_timeout_s: int = TEST_TIMEOUT_S,
    ) -> None:
        self.memory = memory
        self.cpus = cpus
        self.install_timeout_s = install_timeout_s
        self.test_timeout_s = test_timeout_s

    def available(self) -> bool:
        return docker_available()

    def _run_container(
        self,
        image: str,
        workspace: Path,
        command: str,
        network: str,
        timeout_s: int,
        env: dict[str, str] | None = None,
    ) -> tuple[int | None, str, float]:
        args = [
            "docker",  # noqa: S607 -- docker binary from PATH
            "run",
            "--rm",
            "--network",
            network,
            "--memory",
            self.memory,
            "--cpus",
            self.cpus,
            "--read-only",
            "--tmpfs",
            "/tmp:rw,size=256m",  # noqa: S108 -- container tmpfs mount, not a host temp file
            "-v",
            f"{workspace}:/work",
            "-w",
            "/work",
            "-e",
            "HOME=/tmp",
        ]
        for key, value in (env or {}).items():
            args += ["-e", f"{key}={value}"]
        args += [image, "sh", "-c", command]
        started = time.monotonic()
        try:
            proc = subprocess.run(  # noqa: S603 -- fixed docker binary, no shell
                args, capture_output=True, text=True, timeout=timeout_s
            )
        except subprocess.TimeoutExpired as e:
            out = (_coerce_output(e.stdout) + "\n" + _coerce_output(e.stderr)).strip()
            return None, _tail(f"TIMEOUT after {timeout_s}s\n{out}"), time.monotonic() - started
        except OSError as e:
            return None, f"could not start container: {e}", time.monotonic() - started
        duration = time.monotonic() - started
        return proc.returncode, _tail((proc.stdout + "\n" + proc.stderr).strip()), duration

    def validate(
        self,
        diff: str,
        snapshot: Path,
        commands: list[tuple[str, str]],
        timeout_s: int = TEST_TIMEOUT_S,
    ) -> SandboxResult:
        from nexus.sandbox.validate import apply_diff_to_copy, detect_commands

        sandbox_id = f"docker-{uuid.uuid4().hex[:8]}"
        if not self.available():
            return SandboxResult(
                status="unavailable",
                sandbox_id="unavailable",
                image="",
                commands=(),
                summary="Docker daemon unreachable; validation cannot run. "
                "No test result is fabricated.",
            )
        workspace = Path(tempfile.mkdtemp(prefix="nexus-sandbox-"))
        try:
            ok, message = apply_diff_to_copy(diff, snapshot, workspace)
            if not ok:
                return SandboxResult(
                    status="error",
                    sandbox_id=sandbox_id,
                    image="",
                    commands=(),
                    summary=f"diff would not apply: {message}",
                )
            if not commands:
                commands = detect_commands(workspace)
            if not commands:
                return SandboxResult(
                    status="error",
                    sandbox_id=sandbox_id,
                    image="",
                    commands=(),
                    summary="no test command detected (no pytest config/tests "
                    "or package.json test script); refusing to claim a pass.",
                )
            results: list[CommandResult] = []
            images: list[str] = []
            for image, command in commands:
                images.append(image)
                if image == "python" and (workspace / "requirements.txt").exists():
                    code, log, dur = self._run_container(
                        PYTHON_IMAGE,
                        workspace,
                        "pip install --no-cache-dir -r requirements.txt",
                        network="bridge",
                        timeout_s=self.install_timeout_s,
                    )
                    results.append(
                        CommandResult(
                            command="pip install -r requirements.txt",
                            exit_code=code,
                            status="passed" if code == 0 else "error",
                            log_tail=log,
                            duration_s=round(dur, 1),
                            test_counts={},
                        )
                    )
                    if code != 0:
                        break
                if image == "node" and (workspace / "package-lock.json").exists():
                    code, log, dur = self._run_container(
                        NODE_IMAGE,
                        workspace,
                        "npm ci --no-audit --no-fund",
                        network="bridge",
                        timeout_s=self.install_timeout_s,
                    )
                    results.append(
                        CommandResult(
                            command="npm ci",
                            exit_code=code,
                            status="passed" if code == 0 else "error",
                            log_tail=log,
                            duration_s=round(dur, 1),
                            test_counts={},
                        )
                    )
                    if code != 0:
                        break
                full_image = PYTHON_IMAGE if image == "python" else NODE_IMAGE
                code, log, dur = self._run_container(
                    full_image,
                    workspace,
                    command,
                    network="none",
                    timeout_s=min(timeout_s, self.test_timeout_s),
                    env={"CI": "true"} if image == "node" else None,
                )
                counts = parse_test_counts(log) if code == 0 else {}
                results.append(
                    CommandResult(
                        command=command,
                        exit_code=code,
                        status="passed" if code == 0 else ("error" if code is None else "failed"),
                        log_tail=log,
                        duration_s=round(dur, 1),
                        test_counts=counts,
                    )
                )
                if code != 0:
                    break
            status = (
                "passed"
                if all(r.status == "passed" for r in results)
                else ("failed" if any(r.status == "failed" for r in results) else "error")
            )
            summary = f"{len(results)} command(s) in {sandbox_id}; " + (
                "all passed" if status == "passed" else f"ended {status}"
            )
            return SandboxResult(
                status=status,
                sandbox_id=sandbox_id,
                image=",".join(dict.fromkeys(images)),
                commands=tuple(results),
                summary=summary,
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


class FakeRunner:
    """Scripted runner for tests only. Never used in production paths."""

    name = "fake"

    def __init__(self, result: SandboxResult) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    def available(self) -> bool:
        return True

    def validate(
        self,
        diff: str,
        snapshot: Path,
        commands: list[tuple[str, str]],
        timeout_s: int = TEST_TIMEOUT_S,
    ) -> SandboxResult:
        self.calls.append({"diff_len": len(diff), "commands": list(commands)})
        return self._result


def parse_test_counts(log: str) -> dict[str, int]:
    """Parse pytest-style `X passed, Y failed, Z error` summaries from a log tail."""
    import re

    counts: dict[str, int] = {}
    matches = re.findall(r"(\d+)\s+(passed|failed|error|skipped|xfailed)", log)
    for value, kind in matches:
        key = "errors" if kind == "error" else kind
        counts[key] = counts.get(key, 0) + int(value)
    return counts
