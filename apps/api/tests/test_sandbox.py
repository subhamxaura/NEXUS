"""Sandbox unit tests: detection, parsing, LF-safe apply, unavailable path."""

from pathlib import Path

import pytest

from nexus.sandbox.runner import (
    CommandResult,
    DockerRunner,
    FakeRunner,
    SandboxResult,
    docker_available,
    parse_test_counts,
)
from nexus.sandbox.validate import apply_diff_to_copy, copy_snapshot, detect_commands


def test_parse_test_counts() -> None:
    assert parse_test_counts("3 passed in 0.5s") == {"passed": 3}
    assert parse_test_counts("2 failed, 5 passed, 1 skipped") == {
        "failed": 2,
        "passed": 5,
        "skipped": 1,
    }
    assert parse_test_counts("no summary here") == {}


def test_detect_python_pytest(tmp_path: Path) -> None:
    (tmp_path / "test_foo.py").write_text("def test_x(): pass\n")
    assert detect_commands(tmp_path) == [("python", "python -m pytest -q")]


def test_detect_node(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')
    assert detect_commands(tmp_path) == [("node", "npm test")]


def test_detect_skips_placeholder_scripts(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"test": "echo \\"no tests\\""}}')
    assert detect_commands(tmp_path) == []


def test_detect_nothing(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hi")
    assert detect_commands(tmp_path) == []


def test_copy_snapshot_skips_git(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / ".git").mkdir(parents=True)
    (src / ".git" / "HEAD").write_text("ref")
    (src / "a.py").write_text("x = 1\n")
    dest = tmp_path / "dest"
    dest.mkdir()
    copy_snapshot(src, dest)
    assert (dest / "a.py").exists()
    assert not (dest / ".git").exists()


def test_apply_diff_lf_safe_with_crlf_patch(tmp_path: Path) -> None:
    """Regression: CRLF patch bytes (Windows temp files) must still apply."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("x = 1\ny = 2\n", newline="")
    dest = tmp_path / "dest"
    dest.mkdir()
    diff = ("--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n x = 1\n-y = 2\n+y = 3\n").replace(
        "\n", "\r\n"
    )
    ok, message = apply_diff_to_copy(diff, src, dest)
    assert ok, message
    assert (dest / "a.py").read_text() == "x = 1\ny = 3\n"


def test_docker_unavailable_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import nexus.sandbox.runner as runner_mod

    monkeypatch.setattr(runner_mod, "docker_available", lambda timeout_s=10: False)
    runner = DockerRunner()
    assert runner.available() is False
    result = runner.validate("diff", tmp_path, [])
    assert result.status == "unavailable"
    assert result.commands == ()


def test_fake_runner_passthrough() -> None:
    expected = SandboxResult(
        status="passed", sandbox_id="s", image="python", commands=(), summary="ok"
    )
    fake = FakeRunner(expected)
    assert fake.available() is True
    assert fake.validate("d", Path("."), []) == expected
    assert fake.calls and fake.calls[0]["diff_len"] == 1


def test_docker_probe_bool() -> None:
    assert isinstance(docker_available(), bool)


def test_command_result_defaults() -> None:
    cmd = CommandResult(
        command="pytest", exit_code=0, status="passed", log_tail="", duration_s=0.0, test_counts={}
    )
    assert cmd.exit_code == 0
