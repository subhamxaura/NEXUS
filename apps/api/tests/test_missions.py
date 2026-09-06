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
from nexus.services.missions import check_diff
from tests.test_agents import ARCHITECT_OUT, CODER_OUT, SCOUT_OUT, SECURITY_OUT

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
        }
    )
    monkeypatch.setattr(factory, "get_client", lambda: fake)
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


@pytest.mark.usefixtures("_fresh_db", "cloned", "fake_llm")
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
    assert mission["status"] == "patch_ready"
    assert [s["agent"] for s in mission["plan"]["steps"]] == [
        "scout",
        "architect",
        "security",
        "coder",
    ]
    mission_id = mission["id"]

    detail = client.get(f"/api/v1/missions/{mission_id}", headers=auth).json()
    assert [t["agent_name"] for t in detail["tasks"]] == [
        "orchestrator",
        "scout",
        "architect",
        "security",
        "coder",
    ]
    assert all(t["status"] == "completed" for t in detail["tasks"])
    assert all(t["prompt_version"] for t in detail["tasks"])
    assert detail["patch"]["applied_state"] == "proposed"
    assert "helpers.py" in detail["patch"]["files_changed"]

    events = client.get(f"/api/v1/missions/{mission_id}/events", headers=auth).json()
    types = [e["event_type"] for e in events]
    assert types[0] == "mission_created"
    assert types[-1] == "mission_completed"
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)
    for agent in ("scout", "architect", "security", "coder"):
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


@pytest.mark.usefixtures("_fresh_db", "cloned", "fake_llm")
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


@pytest.mark.usefixtures("_fresh_db", "cloned", "fake_llm")
def test_cancel_rejects_after_completion(client: TestClient) -> None:
    auth = _login(client, "alice")
    repo_id, finding_id = _setup_repo(client, auth)
    mission_id = client.post(
        f"/api/v1/repos/{repo_id}/missions",
        json={"goal": "x", "finding_id": finding_id},
        headers=auth,
    ).json()["id"]
    r = client.post(f"/api/v1/missions/{mission_id}/cancel", headers=auth)
    assert r.status_code == 409  # patch_ready is terminal in Phase 2
