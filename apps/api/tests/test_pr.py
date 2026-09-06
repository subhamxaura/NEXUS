"""Approval gate, PR creation (mocked GitHub), and webhook tests. No network."""

import hashlib
import hmac
import json
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import nexus.llm.factory as factory
from nexus.core.config import settings
from nexus.github import client as gh
from nexus.github.clone import CloneResult
from nexus.llm.fake import FakeLLMClient
from nexus.main import app
from nexus.sandbox.runner import FakeRunner
from nexus.services.pr import build_pr_body
from tests.test_agents import ARCHITECT_OUT, CODER_OUT, SCOUT_OUT, SECURITY_OUT
from tests.test_missions import PASSED_SANDBOX, REVIEWER_OUT

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _fake_clone(url: str, timeout_s: int = 180) -> CloneResult:
    _ = (url, timeout_s)
    workdir = Path(tempfile.mkdtemp(prefix="nexus-test-clone-"))
    shutil.copytree(FIXTURE, workdir, dirs_exist_ok=True)
    return CloneResult(workdir=workdir, sha="abc123testsha")


@pytest.fixture
def harness(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, object]]:
    import nexus.services.analysis as analysis_svc
    import nexus.services.missions as missions_svc

    monkeypatch.setattr(analysis_svc.gitclone, "clone", _fake_clone)
    monkeypatch.setattr(analysis_svc, "ensure_workspace", lambda repo, sha: FIXTURE)
    fake_llm = FakeLLMClient(
        {
            "scout": [SCOUT_OUT],
            "architect": [ARCHITECT_OUT],
            "security": [SECURITY_OUT],
            "coder": [CODER_OUT],
            "reviewer": [REVIEWER_OUT],
        }
    )
    monkeypatch.setattr(factory, "get_client", lambda: fake_llm)
    monkeypatch.setattr(missions_svc, "_default_sandbox", lambda: FakeRunner(PASSED_SANDBOX))

    r = client.post("/api/v1/auth/dev-login", json={"login": "alice"})
    auth = {"Authorization": f"Bearer {r.json()['token']}"}
    repo_id = client.post("/api/v1/repos", json={"owner": "o", "name": "r"}, headers=auth).json()[
        "id"
    ]
    assert client.post(f"/api/v1/repos/{repo_id}/analyze", headers=auth).status_code == 200
    finding_id = client.get(f"/api/v1/repos/{repo_id}/findings", headers=auth).json()[0]["id"]
    mission_id = client.post(
        f"/api/v1/repos/{repo_id}/missions",
        json={"goal": "Fix the highest-risk issue.", "finding_id": finding_id},
        headers=auth,
    ).json()["id"]
    yield {"client": client, "auth": auth, "repo_id": repo_id, "mission_id": mission_id}


def _awaiting(harness: dict[str, object]) -> None:
    client = harness["client"]
    auth = harness["auth"]
    mission_id = harness["mission_id"]
    assert isinstance(client, TestClient) and isinstance(auth, dict) and isinstance(mission_id, int)
    detail = client.get(f"/api/v1/missions/{mission_id}", headers=auth).json()
    assert detail["mission"]["status"] == "awaiting_approval", detail["mission"]


@pytest.mark.usefixtures("_fresh_db")
def test_approve_requires_token(harness: dict[str, object]) -> None:
    _awaiting(harness)
    client = harness["client"]
    auth = harness["auth"]
    mission_id = harness["mission_id"]
    assert isinstance(client, TestClient) and isinstance(auth, dict) and isinstance(mission_id, int)
    r = client.post(f"/api/v1/missions/{mission_id}/approve", json={}, headers=auth)
    assert r.status_code == 409
    assert "token" in r.json()["detail"].lower()


@pytest.mark.usefixtures("_fresh_db")
def test_approve_unknown_mission_404(harness: dict[str, object]) -> None:
    client = harness["client"]
    auth = harness["auth"]
    assert isinstance(client, TestClient) and isinstance(auth, dict)
    assert client.post("/api/v1/missions/99999/approve", json={}, headers=auth).status_code == 404


@pytest.mark.usefixtures("_fresh_db")
def test_approve_happy_path_mocked_github(
    harness: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    _awaiting(harness)
    client = harness["client"]
    auth = harness["auth"]
    mission_id = harness["mission_id"]
    assert isinstance(client, TestClient) and isinstance(auth, dict) and isinstance(mission_id, int)

    calls: dict[str, object] = {}
    # Deliberately fake, non-secret-looking token value (also safe from scanners).
    fake_token = "test-token-abc"

    async def _base(owner: str, name: str, tok: str) -> str:
        calls["base_args"] = (owner, name, tok[:4])
        assert tok == fake_token
        return "main"

    def _push(
        owner: str,
        name: str,
        base: str,
        branch: str,
        diff: str,
        files: list[str],
        message: str,
        tok: str,
    ) -> gh.PreparedBranch:
        _ = tok
        calls["push"] = {"branch": branch, "base": base, "files": files, "message": message}
        assert branch.startswith(f"nexus/{mission_id}-")
        assert branch != base
        assert "Co-authored-by: NEXUS <bot@nexus>" in message
        assert fake_token not in message
        workdir = Path(tempfile.mkdtemp(prefix="nexus-test-pr-"))
        return gh.PreparedBranch(workdir=workdir, branch=branch, base=base, commit_sha="deadbee")

    async def _pr(
        owner: str, name: str, head: str, base: str, title: str, body: str, tok: str
    ) -> gh.CreatedPR:
        _ = tok
        calls["pr"] = {"head": head, "base": base, "title": title, "body": body}
        assert head != base
        assert "## Independent review verdict" in body
        assert "## Validation results" in body
        assert "## NEXUS mission trace" in body
        return gh.CreatedPR(number=42, url="https://github.com/o/r/pull/42")

    monkeypatch.setattr(gh, "fetch_default_branch", _base)
    monkeypatch.setattr(gh, "push_branch", _push)
    monkeypatch.setattr(gh, "create_pull_request", _pr)

    r = client.post(
        f"/api/v1/missions/{mission_id}/approve",
        json={"github_token": fake_token},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["pr_number"] == 42
    assert r.json()["branch"].startswith(f"nexus/{mission_id}-")

    detail = client.get(f"/api/v1/missions/{mission_id}", headers=auth).json()
    assert detail["mission"]["status"] == "pr_created"
    assert detail["pull_request"]["url"] == "https://github.com/o/r/pull/42"

    r = client.post(
        f"/api/v1/missions/{mission_id}/approve",
        json={"github_token": fake_token},
        headers=auth,
    )
    assert r.status_code == 409  # terminal: no double PR


@pytest.mark.usefixtures("_fresh_db")
def test_approve_forbidden_for_other_user(harness: dict[str, object], client: TestClient) -> None:
    _awaiting(harness)
    mission_id = harness["mission_id"]
    assert isinstance(mission_id, int)
    token = client.post("/api/v1/auth/dev-login", json={"login": "bob"}).json()["token"]
    bob = {"Authorization": f"Bearer {token}"}
    r = client.post(f"/api/v1/missions/{mission_id}/approve", json={}, headers=bob)
    assert r.status_code == 404


def test_pr_body_sections() -> None:
    body = build_pr_body(
        goal="Fix X",
        finding={"type": "secret-hit", "severity": "high", "path": "a.py", "message": "m"},
        proposal={"summary": "s", "impact_dependents": ["b.py"], "risks": ["r"]},
        validation={
            "status": "passed",
            "sandbox_id": "s",
            "image": "i",
            "commands": [{"command": "pytest", "exit_code": 0, "status": "passed"}],
        },
        review={"verdict": "approve", "score": 90, "comments": ["c"]},
        files_changed=["a.py"],
        mission_id=7,
        commit_sha="abc123",
        analyzer_version="v0.1.0",
    )
    for section in (
        "## Goal",
        "## Finding addressed",
        "## What changed",
        "## Why this approach",
        "## Impact analysis",
        "## Validation results",
        "## Independent review verdict",
        "## Known limitations",
        "## NEXUS mission trace",
    ):
        assert section in body


def test_slugify_and_commit_message() -> None:
    assert gh.slugify("Fix The Thing! Now?") == "fix-the-thing-now"
    assert gh.slugify("") == "change"
    msg = gh.commit_message("Do X", True)
    assert msg.startswith("fix(nexus):") and "Co-authored-by: NEXUS <bot@nexus>" in msg
    assert gh.commit_message("Do X", False).startswith("chore(nexus):")


def test_push_branch_refuses_non_nexus_branch(tmp_path: Path) -> None:
    try:
        gh.push_branch("o", "n", "main", "main", "diff", [], "msg", "tok")
    except gh.GitHubError as e:
        assert "non-nexus" in str(e)
    else:
        raise AssertionError("expected refusal")


def test_git_error_scrubs_token(tmp_path: Path) -> None:
    with pytest.raises(gh.GitHubError) as excinfo:
        gh._run_git(["rev-parse", "definitely-not-a-ref-xyz"], tmp_path, "SECRET123")
    assert "SECRET123" not in str(excinfo.value)


def test_webhook_requires_secret(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "github_webhook_secret", "")
    r = client.post("/webhooks/github", json={})
    assert r.status_code == 400


@pytest.mark.usefixtures("_fresh_db")
def test_webhook_push_marks_stale(
    harness: dict[str, object], client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "github_webhook_secret", "s3cr3t")
    auth = harness["auth"]
    repo_id = harness["repo_id"]
    assert isinstance(auth, dict) and isinstance(repo_id, int)
    before = client.get("/api/v1/repos", headers=auth).json()
    assert before[0]["last_analyzed_sha"] is not None

    payload = {"ref": "refs/heads/main", "repository": {"full_name": "o/r"}}
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"s3cr3t", raw, hashlib.sha256).hexdigest()
    r = client.post(
        "/webhooks/github",
        content=raw,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "push",
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "marked-stale"
    after = client.get("/api/v1/repos", headers=auth).json()
    assert after[0]["last_analyzed_sha"] is None

    bad = client.post(
        "/webhooks/github",
        content=raw,
        headers={
            "X-Hub-Signature-256": "sha256=bad",
            "X-GitHub-Event": "push",
            "Content-Type": "application/json",
        },
    )
    assert bad.status_code == 401
