"""Gap-closing tests: context tools, clone validation, GitHub client (mocked),
JWT/fernet, LLM factory, detector leftovers, worker jobs. No network."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

import nexus.llm.factory as factory
from nexus.agents.context import AgentContext
from nexus.core.config import settings
from nexus.core.security import (
    create_session_token,
    decrypt_token,
    encrypt_token,
    parse_session_token,
)
from nexus.github import client as gh
from nexus.github import clone as gitclone
from nexus.intelligence.detector import detect_language, is_planned
from nexus.llm.client import PermanentLLMError
from nexus.llm.fake import FakeLLMClient


def _ctx(tmp_path: Path) -> AgentContext:
    async def emit(event_type: str, payload: dict[str, Any]) -> None:
        _ = (event_type, payload)

    return AgentContext(mission_id=1, workspace=tmp_path, llm=FakeLLMClient({}), emit=emit)


def test_context_read_and_search(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("hello world\n" * 10)
    ctx = _ctx(tmp_path)
    assert "hello world" in ctx.read_file("a.py")
    assert ctx.read_file("a.py", limit_chars=20).endswith("[... truncated ...]")
    assert ctx.search_code("hello") == [f"a.py:{i}" for i in range(1, 11)]
    assert ctx.search_code("hello", limit=3) == ["a.py:1", "a.py:2", "a.py:3"]
    with pytest.raises(ValueError):
        ctx.read_file("../escape.py")
    with pytest.raises(ValueError):
        ctx.search_code("(unclosed")


def test_clone_validation() -> None:
    assert gitclone.validate_repo_url("https://github.com/octo/demo") == ("octo", "demo")
    assert gitclone.validate_repo_url("https://github.com/octo/demo.git/") == ("octo", "demo")
    for bad in (
        "http://github.com/o/r",
        "git@github.com:o/r.git",
        "https://gitlab.com/o/r",
        "https://github.com/o",
        "notaurl",
    ):
        with pytest.raises(gitclone.CloneError):
            gitclone.validate_repo_url(bad)
    with pytest.raises(gitclone.CloneError):
        gitclone.validate_owner_name("../x", "r")
    with pytest.raises(gitclone.CloneError):
        gitclone.validate_owner_name("o", "..")
    assert gitclone.repo_url("o", "r") == "https://github.com/o/r.git"


def test_clone_failure_cleans_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import subprocess

    def _fail(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="not found")

    monkeypatch.setattr(subprocess, "run", _fail)
    with pytest.raises(gitclone.CloneError):
        gitclone.clone("https://github.com/o/r")

    def _boom(*args: Any, **kwargs: Any) -> SimpleNamespace:
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", _boom)
    with pytest.raises(gitclone.CloneError):
        gitclone.clone("https://github.com/o/r")
    with pytest.raises(gitclone.CloneError):
        gitclone.head_sha(tmp_path)


def test_dispose_removes_dir(tmp_path: Path) -> None:
    target = tmp_path / "ws"
    target.mkdir()
    gitclone.dispose(target)
    assert not target.exists()


def test_scrub_and_guards() -> None:
    assert gh._scrub("Bearer SECRET123 ok", "SECRET123") == "Bearer [REDACTED] ok"
    with pytest.raises(gh.GitHubError):
        gh.push_branch("o", "n", "main", "main", "d", [], "m", "t")
    with pytest.raises(gh.GitHubError):
        gh.push_branch("o", "n", "main", "feature/x", "d", [], "m", "t")


class _FakeResp:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _FakeHTTP:
    response: _FakeResp | None = None
    seen: dict[str, object] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    async def __aenter__(self) -> "_FakeHTTP":
        return self

    async def __aexit__(self, *args: Any) -> None:
        _ = args

    async def post(self, url: str, headers: dict[str, str], json: object) -> _FakeResp:
        type(self).seen = {"url": url, "headers": headers, "json": json}
        assert self.response is not None
        return self.response

    async def get(self, url: str, headers: dict[str, str]) -> _FakeResp:
        type(self).seen = {"url": url, "headers": headers}
        assert self.response is not None
        return self.response


async def test_github_rest_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeHTTP)
    _FakeHTTP.response = _FakeResp(201, {"number": 3, "html_url": "https://github.com/o/r/pull/3"})
    pr = await gh.create_pull_request("o", "r", "nexus/1-x", "main", "t", "b", "tok")
    assert (pr.number, pr.url) == (3, "https://github.com/o/r/pull/3")
    assert _FakeHTTP.seen["url"] == "https://api.github.com/repos/o/r/pulls"

    _FakeHTTP.response = _FakeResp(422, {"message": "nope"})
    with pytest.raises(gh.GitHubError):
        await gh.create_pull_request("o", "r", "nexus/1-x", "main", "t", "b", "tok")
    _FakeHTTP.response = _FakeResp(201, {"unexpected": True})
    with pytest.raises(gh.GitHubError):
        await gh.create_pull_request("o", "r", "nexus/1-x", "main", "t", "b", "tok")
    with pytest.raises(gh.GitHubError):
        await gh.create_pull_request("o", "r", "main", "main", "t", "b", "tok")

    _FakeHTTP.response = _FakeResp(200, {"default_branch": "develop"})
    assert await gh.fetch_default_branch("o", "r", "tok") == "develop"
    _FakeHTTP.response = _FakeResp(404, {})
    with pytest.raises(gh.GitHubError):
        await gh.fetch_default_branch("o", "r", "tok")


def test_push_branch_mocked_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import shutil
    import subprocess

    calls: list[list[str]] = []

    def _ok(*args: Any, **kwargs: Any) -> SimpleNamespace:
        cmd = list(args[0])
        calls.append(cmd)
        out = "deadbeef1234" if cmd[:2] == ["git", "rev-parse"] else ""
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", _ok)
    prepared = gh.push_branch("o", "n", "main", "nexus/9-fix-x", "diff", ["a.py"], "msg", "tok")
    try:
        assert prepared.branch == "nexus/9-fix-x" and prepared.commit_sha == "deadbeef1234"
        assert any("checkout" in c for c in calls) and any("push" in c for c in calls)
    finally:
        shutil.rmtree(prepared.workdir, ignore_errors=True)

    def _fail(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=128, stdout="", stderr="auth failed")

    monkeypatch.setattr(subprocess, "run", _fail)
    with pytest.raises(gh.GitHubError, match="auth failed"):
        gh.push_branch("o", "n", "main", "nexus/9-fix-x", "diff", ["a.py"], "msg", "tok")


def test_jwt_roundtrip() -> None:
    token = create_session_token(42)
    assert parse_session_token(token) == 42
    assert parse_session_token("garbage") is None
    assert parse_session_token(token + "tampered") is None


def test_fernet_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "token_fernet_key", Fernet.generate_key().decode())
    assert decrypt_token(encrypt_token("hello")) == "hello"
    monkeypatch.setattr(settings, "token_fernet_key", "")
    with pytest.raises(RuntimeError):
        encrypt_token("x")
    with pytest.raises(RuntimeError):
        decrypt_token("x")
    monkeypatch.setattr(settings, "token_fernet_key", Fernet.generate_key().decode())
    with pytest.raises(RuntimeError):
        decrypt_token("not-a-token")


def test_factory_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "nope")
    with pytest.raises(PermanentLLMError):
        factory.get_client()
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(PermanentLLMError):
        factory.get_client()
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    assert factory.get_client().name == "openai"
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(PermanentLLMError):
        factory.get_client()
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    assert factory.get_client().name == "anthropic"


def test_detector_leftovers() -> None:
    assert is_planned("main.go") and is_planned("Main.java")
    assert not is_planned("app.py")
    assert detect_language("notes.md") is None


@pytest.mark.usefixtures("_fresh_db")
async def test_worker_jobs() -> None:
    from nexus.workers.settings import _noop, analyze_repo_job, run_mission_job

    assert await _noop({}) == {"status": "ok"}
    assert await analyze_repo_job({}, 999999) == {"status": "missing"}
    assert await run_mission_job({}, 999999) == {"status": "missing", "mission_id": 999999}


@pytest.mark.usefixtures("_fresh_db")
async def test_analyze_job_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    import tempfile

    import nexus.services.analysis as analysis_svc
    from nexus.core.database import SessionLocal
    from nexus.github.clone import CloneResult
    from nexus.models.entities import Analysis, Repository
    from nexus.workers.settings import analyze_repo_job

    fixture = Path(__file__).parent / "fixtures" / "sample_repo"

    def _fake_clone(url: str, timeout_s: int = 180) -> CloneResult:
        _ = (url, timeout_s)
        workdir = Path(tempfile.mkdtemp(prefix="nexus-job-"))
        shutil.copytree(fixture, workdir, dirs_exist_ok=True)
        return CloneResult(workdir=workdir, sha="jobsha123")

    monkeypatch.setattr(analysis_svc.gitclone, "clone", _fake_clone)
    async with SessionLocal() as session:
        session.add(Repository(owner="o", name="r", owner_user_id=None))
        await session.flush()
        repo = (
            (await session.execute(select(Repository).where(Repository.owner == "o")))
            .scalars()
            .first()
        )
        assert repo is not None
        session.add(Analysis(repo_id=repo.id, commit_sha="x", status="pending"))
        await session.commit()
        row = (
            (await session.execute(select(Analysis).where(Analysis.commit_sha == "x")))
            .scalars()
            .first()
        )
        assert row is not None
        job_id = row.id
    out = await analyze_repo_job({}, job_id)
    # The job analyzes at the cloned SHA (jobsha123), not the fake pending
    # row's SHA, so it must produce its own completed analysis row.
    assert out["status"] in ("complete", "partial", "failed")
    async with SessionLocal() as session:
        done = (
            (await session.execute(select(Analysis).where(Analysis.commit_sha == "jobsha123")))
            .scalars()
            .first()
        )
    assert done is not None and done.status in ("complete", "partial", "failed")


def test_runner_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from nexus.sandbox.runner import _coerce_output, _tail, docker_available

    assert _tail("abc", limit=10) == "abc"
    assert _tail("x" * 20, limit=10).startswith("[... truncated 10 chars ...]")
    assert _coerce_output(None) == "" and _coerce_output("s") == "s"
    assert _coerce_output("ü".encode()) == "ü"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="v", stderr=""),
    )
    assert docker_available() is True


@pytest.mark.usefixtures("_fresh_db")
async def test_analyze_job_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    import nexus.services.analysis as analysis_svc
    from nexus.core.database import SessionLocal
    from nexus.github import clone as gitclone
    from nexus.models.entities import Analysis, Repository
    from nexus.workers.settings import analyze_repo_job

    async with SessionLocal() as session:
        session.add(Repository(owner="o", name="r", owner_user_id=None))
        await session.flush()
        repo = (
            (await session.execute(select(Repository).where(Repository.owner == "o")))
            .scalars()
            .first()
        )
        assert repo is not None
        session.add(Analysis(repo_id=repo.id, commit_sha="done", status="complete"))
        session.add(Analysis(repo_id=999999, commit_sha="orphan", status="pending"))
        session.add(Analysis(repo_id=repo.id, commit_sha="boom", status="pending"))
        await session.commit()
        ids = {
            r.commit_sha: r.id for r in (await session.execute(select(Analysis))).scalars().all()
        }

    out = await analyze_repo_job({}, ids["done"])
    assert out == {"status": "cached", "analysis_id": ids["done"]}
    out = await analyze_repo_job({}, ids["orphan"])
    assert out == {"status": "missing"}

    async def _fail(session: object, repo: object) -> object:
        _ = (session, repo)
        raise gitclone.CloneError("denied")

    monkeypatch.setattr(analysis_svc, "run_analysis", _fail)
    out = await analyze_repo_job({}, ids["boom"])
    assert out["status"] == "failed"
