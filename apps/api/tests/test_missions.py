"""Mission E2E tests: mocked clone + scripted fake LLM (no network, no real key)."""

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import nexus.llm.factory as factory
from nexus.github.clone import CloneResult
from nexus.llm.client import PermanentLLMError
from nexus.llm.fake import FakeLLMClient
from nexus.main import app
from nexus.sandbox.runner import CommandResult, FakeRunner, SandboxResult, SandboxRunner
from nexus.services.missions import check_diff
from tests.test_agents import ARCHITECT_OUT, CODER_OUT, SCOUT_OUT, SECURITY_OUT

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"

REVIEWER_OUT = {
    "verdict": "approve",
    "score": 85,
    "comments": ["minimal one-line change; validation passed"],
    "concerns": [],
}

PASSED_SANDBOX = SandboxResult(
    status="passed",
    sandbox_id="fake-1",
    image="python",
    commands=(
        CommandResult(
            command="python -m pytest -q",
            exit_code=0,
            status="passed",
            log_tail="1 passed",
            duration_s=1.0,
            test_counts={"passed": 1},
        ),
    ),
    summary="all passed",
)


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
def cloned(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    import nexus.services.analysis as svc

    monkeypatch.setattr(svc.gitclone, "clone", _fake_clone)
    monkeypatch.setattr(svc, "ensure_workspace", lambda repo, sha: FIXTURE)
    yield


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeLLMClient]:
    fake = FakeLLMClient(
        {
            "scout": [SCOUT_OUT],
            "architect": [ARCHITECT_OUT],
            "security": [SECURITY_OUT],
            "coder": [CODER_OUT],
            "reviewer": [REVIEWER_OUT],
        }
    )
    monkeypatch.setattr(factory, "get_client", lambda: fake)
    yield fake


@pytest.fixture
def sandbox_passed(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeRunner]:
    import nexus.services.missions as missions

    fake = FakeRunner(PASSED_SANDBOX)
    monkeypatch.setattr(missions, "_default_sandbox", lambda: fake)
    yield fake


def _login(client: TestClient, name: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/dev-login", json={"login": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _setup_repo(client: TestClient, auth: dict[str, str]) -> tuple[int, int]:
    repo_id = client.post("/api/v1/repos", json={"owner": "o", "name": "r"}, headers=auth).json()[
        "id"
    ]
    assert client.post(f"/api/v1/repos/{repo_id}/analyze", headers=auth).status_code == 200
    findings = client.get(f"/api/v1/repos/{repo_id}/findings", headers=auth).json()
    assert findings, "fixture must yield findings"
    return repo_id, findings[0]["id"]


def test_canned_diff_applies_to_fixture() -> None:
    ok, message, files = check_diff(CODER_OUT["diff"], FIXTURE)  # type: ignore[arg-type]
    assert ok, message
    assert files == ["helpers.py"]


@pytest.mark.usefixtures("_fresh_db", "cloned", "fake_llm", "sandbox_passed")
def test_mission_happy_path(client: TestClient) -> None:
    auth = _login(client, "alice")
    repo_id, finding_id = _setup_repo(client, auth)

    r = client.post(
        f"/api/v1/repos/{repo_id}/missions",
        json={"goal": "Fix the highest-risk issue.", "finding_id": finding_id},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    mission = r.json()
    assert mission["status"] == "awaiting_approval"
    assert [s["agent"] for s in mission["plan"]["steps"]] == [
        "scout",
        "architect",
        "security",
        "coder",
        "tester",
        "reviewer",
    ]
    mission_id = mission["id"]

    detail = client.get(f"/api/v1/missions/{mission_id}", headers=auth).json()
    assert [t["agent_name"] for t in detail["tasks"]] == [
        "orchestrator",
        "scout",
        "architect",
        "security",
        "coder",
        "tester",
        "reviewer",
    ]
    assert all(t["status"] == "completed" for t in detail["tasks"])
    assert all(t["prompt_version"] for t in detail["tasks"])
    assert detail["patch"]["applied_state"] == "reviewed"
    assert "helpers.py" in detail["patch"]["files_changed"]
    assert detail["review"]["verdict"] == "approve"
    assert len(detail["validation_runs"]) == 1
    assert detail["validation_runs"][0]["status"] == "passed"
    assert detail["pull_request"] is None  # no PR without human approval

    events = client.get(f"/api/v1/missions/{mission_id}/events", headers=auth).json()
    types = [e["event_type"] for e in events]
    assert types[0] == "mission_created"
    assert types[-1] == "mission_completed"
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)
    for agent in ("scout", "architect", "security", "coder", "tester", "reviewer"):
        assert any(
            e["event_type"] == "started" and (e["payload"].get("agent") == agent) for e in events
        )
        assert any(
            e["event_type"] == "completed" and (e["payload"].get("agent") == agent) for e in events
        )


@pytest.mark.usefixtures("_fresh_db", "cloned")
def test_security_block_ends_needs_human(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    risky = dict(SECURITY_OUT, verdict="risky", concerns=["touches eval()"], worsens_security=True)
    fake = FakeLLMClient({"scout": [SCOUT_OUT], "architect": [ARCHITECT_OUT], "security": [risky]})
    monkeypatch.setattr(factory, "get_client", lambda: fake)
    auth = _login(client, "alice")
    repo_id, finding_id = _setup_repo(client, auth)

    r = client.post(
        f"/api/v1/repos/{repo_id}/missions",
        json={"goal": "Fix it.", "finding_id": finding_id},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "needs_human"
    assert r.json()["result"]["reason"] == "security_blocked"

    detail = client.get(f"/api/v1/missions/{r.json()['id']}", headers=auth).json()
    coder_tasks = [t for t in detail["tasks"] if t["agent_name"] == "coder"]
    assert len(coder_tasks) == 1 and coder_tasks[0]["status"] == "blocked"
    assert detail["patch"] is None


@pytest.mark.usefixtures("_fresh_db", "cloned")
def test_invalid_diff_rejected_after_repair(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = dict(CODER_OUT, diff="not a diff at all", files_changed=["helpers.py"])
    fake = FakeLLMClient(
        {
            "scout": [SCOUT_OUT],
            "architect": [ARCHITECT_OUT],
            "security": [SECURITY_OUT],
            "coder": [bad, bad],
        }
    )
    monkeypatch.setattr(factory, "get_client", lambda: fake)
    auth = _login(client, "alice")
    repo_id, finding_id = _setup_repo(client, auth)

    r = client.post(
        f"/api/v1/repos/{repo_id}/missions",
        json={"goal": "Fix it.", "finding_id": finding_id},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "needs_human"
    assert r.json()["result"]["reason"] == "diff_rejected"


@pytest.mark.usefixtures("_fresh_db", "cloned")
def test_llm_unconfigured_needs_human(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise() -> FakeLLMClient:
        raise PermanentLLMError("OPENAI_API_KEY is not configured")

    monkeypatch.setattr(factory, "get_client", _raise)
    auth = _login(client, "alice")
    repo_id, finding_id = _setup_repo(client, auth)
    r = client.post(
        f"/api/v1/repos/{repo_id}/missions",
        json={"goal": "Fix it.", "finding_id": finding_id},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "needs_human"
    assert r.json()["result"]["reason"] == "llm_unconfigured"


@pytest.mark.usefixtures("_fresh_db", "cloned", "fake_llm", "sandbox_passed")
def test_mission_requires_analysis_and_ownership(client: TestClient) -> None:
    alice = _login(client, "alice")
    bob = _login(client, "bob")
    repo_id = client.post("/api/v1/repos", json={"owner": "o", "name": "r"}, headers=alice).json()[
        "id"
    ]
    r = client.post(f"/api/v1/repos/{repo_id}/missions", json={"goal": "x"}, headers=alice)
    assert r.status_code == 400  # no analysis yet

    _, finding_id = _setup_repo(client, alice)
    mission_id = client.post(
        f"/api/v1/repos/{repo_id}/missions",
        json={"goal": "x", "finding_id": finding_id},
        headers=alice,
    ).json()["id"]
    assert client.get(f"/api/v1/missions/{mission_id}", headers=bob).status_code == 404
    assert client.get(f"/api/v1/missions/{mission_id}/events", headers=bob).status_code == 404


@pytest.mark.usefixtures("_fresh_db", "cloned", "fake_llm", "sandbox_passed")
def test_cancel_from_awaiting_then_rejects(client: TestClient) -> None:
    auth = _login(client, "alice")
    repo_id, finding_id = _setup_repo(client, auth)
    mission_id = client.post(
        f"/api/v1/repos/{repo_id}/missions",
        json={"goal": "x", "finding_id": finding_id},
        headers=auth,
    ).json()["id"]
    r = client.post(f"/api/v1/missions/{mission_id}/cancel", headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    r = client.post(f"/api/v1/missions/{mission_id}/cancel", headers=auth)
    assert r.status_code == 409  # cancelled is terminal


def _failed_sandbox(reason: str) -> SandboxResult:
    return SandboxResult(
        status="failed",
        sandbox_id="fake-fail",
        image="python",
        commands=(
            CommandResult(
                command="python -m pytest -q",
                exit_code=1,
                status="failed",
                log_tail=f"FAILED test_broken - {reason}",
                duration_s=2.0,
                test_counts={"failed": 1},
            ),
        ),
        summary=f"tests red: {reason}",
    )


class SequencedRunner:
    """Fake sandbox serving queued results (last one repeats)."""

    name = "sequenced"

    def __init__(self, results: list[SandboxResult]) -> None:
        self._results = list(results)
        self.calls: list[str] = []

    def available(self) -> bool:
        return True

    def validate(
        self,
        diff: str,
        snapshot: Path,
        commands: list[tuple[str, str]],
        timeout_s: int = 600,
    ) -> SandboxResult:
        _ = (snapshot, commands, timeout_s)
        self.calls.append(diff)
        if len(self._results) > 1:
            return self._results.pop(0)
        return self._results[0]


def _mission_with(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    scripts: dict[str, list[object]],
    sandbox: SandboxRunner,
) -> dict[str, object]:
    import nexus.services.missions as missions

    monkeypatch.setattr(factory, "get_client", lambda: FakeLLMClient(scripts))
    monkeypatch.setattr(missions, "_default_sandbox", lambda: sandbox)
    auth = _login(client, "alice")
    repo_id, finding_id = _setup_repo(client, auth)
    r = client.post(
        f"/api/v1/repos/{repo_id}/missions",
        json={"goal": "Fix it.", "finding_id": finding_id},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    return {"response": r.json(), "auth": auth}


@pytest.mark.usefixtures("_fresh_db", "cloned")
def test_repair_loop_recovers(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    scripts = {
        "scout": [SCOUT_OUT],
        "architect": [ARCHITECT_OUT],
        "security": [SECURITY_OUT],
        "coder": [CODER_OUT, CODER_OUT],
        "reviewer": [REVIEWER_OUT],
    }
    out = _mission_with(
        client, monkeypatch, scripts, SequencedRunner([_failed_sandbox("boom"), PASSED_SANDBOX])
    )
    assert out["response"]["status"] == "awaiting_approval"
    detail = client.get(f"/api/v1/missions/{out['response']['id']}", headers=out["auth"]).json()  # type: ignore[typeddict-item]
    testers = [t for t in detail["tasks"] if t["agent_name"] == "tester"]
    coders = [t for t in detail["tasks"] if t["agent_name"] == "coder"]
    assert len(testers) == 2 and len(coders) == 2
    assert [t["status"] for t in testers] == ["completed", "completed"]


@pytest.mark.usefixtures("_fresh_db", "cloned")
def test_repair_exhaustion_needs_human(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    scripts = {
        "scout": [SCOUT_OUT],
        "architect": [ARCHITECT_OUT],
        "security": [SECURITY_OUT],
        "coder": [CODER_OUT, CODER_OUT, CODER_OUT],
        "reviewer": [REVIEWER_OUT],
    }
    out = _mission_with(client, monkeypatch, scripts, SequencedRunner([_failed_sandbox("always")]))
    assert out["response"]["status"] == "needs_human"
    assert out["response"]["result"]["reason"] == "validation_failed"
    detail = client.get(f"/api/v1/missions/{out['response']['id']}", headers=out["auth"]).json()  # type: ignore[typeddict-item]
    testers = [t for t in detail["tasks"] if t["agent_name"] == "tester"]
    assert len(testers) == 3  # initial + exactly 2 repairs


@pytest.mark.usefixtures("_fresh_db", "cloned")
def test_sandbox_unavailable_needs_human(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripts = {
        "scout": [SCOUT_OUT],
        "architect": [ARCHITECT_OUT],
        "security": [SECURITY_OUT],
        "coder": [CODER_OUT],
        "reviewer": [REVIEWER_OUT],
    }
    unavailable = SandboxResult(
        status="unavailable",
        sandbox_id="unavailable",
        image="",
        commands=(),
        summary="no docker here",
    )
    out = _mission_with(client, monkeypatch, scripts, FakeRunner(unavailable))
    assert out["response"]["status"] == "needs_human"
    assert out["response"]["result"]["reason"] == "sandbox_unavailable"


@pytest.mark.usefixtures("_fresh_db", "cloned")
def test_reviewer_rejection_blocks_pr(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    reject = {
        "verdict": "request_changes",
        "score": 30,
        "comments": ["tests don't cover the change"],
        "concerns": ["insufficient evidence"],
    }
    scripts = {
        "scout": [SCOUT_OUT],
        "architect": [ARCHITECT_OUT],
        "security": [SECURITY_OUT],
        "coder": [CODER_OUT],
        "reviewer": [reject],
    }
    import nexus.services.missions as missions

    monkeypatch.setattr(factory, "get_client", lambda: FakeLLMClient(scripts))
    monkeypatch.setattr(missions, "_default_sandbox", lambda: FakeRunner(PASSED_SANDBOX))
    auth = _login(client, "alice")
    repo_id, finding_id = _setup_repo(client, auth)
    r = client.post(
        f"/api/v1/repos/{repo_id}/missions",
        json={"goal": "Fix it.", "finding_id": finding_id},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "needs_human"
    assert r.json()["result"]["reason"] == "review_rejected"
    mission_id = r.json()["id"]
    detail = client.get(f"/api/v1/missions/{mission_id}", headers=auth).json()
    assert detail["review"]["verdict"] == "request_changes"
    assert detail["pull_request"] is None
    # Approval gate holds: rejected review can never be approved.
    appr = client.post(
        f"/api/v1/missions/{mission_id}/approve", json={"github_token": "x"}, headers=auth
    )
    assert appr.status_code == 409


@pytest.mark.usefixtures("_fresh_db", "cloned")
def test_retry_appends_trace(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    risky = dict(SECURITY_OUT, verdict="risky", concerns=["x"], worsens_security=True)
    monkeypatch.setattr(
        factory,
        "get_client",
        lambda: FakeLLMClient(
            {
                "scout": [SCOUT_OUT, SCOUT_OUT],
                "architect": [ARCHITECT_OUT, ARCHITECT_OUT],
                "security": [risky, risky],
            }
        ),
    )
    auth = _login(client, "alice")
    repo_id, finding_id = _setup_repo(client, auth)
    mission_id = client.post(
        f"/api/v1/repos/{repo_id}/missions",
        json={"goal": "Fix it.", "finding_id": finding_id},
        headers=auth,
    ).json()["id"]
    before = client.get(f"/api/v1/missions/{mission_id}", headers=auth).json()
    assert before["mission"]["status"] == "needs_human"

    r = client.post(f"/api/v1/missions/{mission_id}/retry", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "needs_human"
    after = client.get(f"/api/v1/missions/{mission_id}", headers=auth).json()
    assert len(after["tasks"]) == 2 * len(before["tasks"])  # trace preserved + appended


@pytest.mark.usefixtures("_fresh_db", "cloned", "fake_llm", "sandbox_passed")
def test_retry_rejects_active_mission(client: TestClient) -> None:
    auth = _login(client, "alice")
    repo_id, finding_id = _setup_repo(client, auth)
    mission_id = client.post(
        f"/api/v1/repos/{repo_id}/missions",
        json={"goal": "Fix it.", "finding_id": finding_id},
        headers=auth,
    ).json()["id"]
    r = client.post(f"/api/v1/missions/{mission_id}/retry", headers=auth)
    assert r.status_code == 409  # awaiting_approval is not retryable
