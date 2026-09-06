"""Phase-1 API tests. Clone is mocked (no network); service+routes are real."""

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexus.core.config import settings
from nexus.github.clone import CloneResult
from nexus.main import app

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


def _login(client: TestClient, name: str) -> str:
    r = client.post("/api/v1/auth/dev-login", json={"login": name})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert isinstance(token, str)
    return f"Bearer {token}"


@pytest.mark.usefixtures("_fresh_db")
def test_unauthorized_rejected(client: TestClient) -> None:
    assert client.get("/api/v1/repos").status_code == 401
    assert client.post("/api/v1/repos", json={"owner": "a", "name": "b"}).status_code == 401


@pytest.mark.usefixtures("_fresh_db", "cloned")
def test_connect_analyze_cache_flow(client: TestClient) -> None:
    auth = {"Authorization": _login(client, "alice")}
    r = client.post("/api/v1/repos", json={"owner": "octo", "name": "demo"}, headers=auth)
    assert r.status_code == 201, r.text
    repo_id = r.json()["id"]

    r = client.post(f"/api/v1/repos/{repo_id}/analyze", headers=auth)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["commit_sha"] == "abc123testsha"
    assert first["status"] in ("complete", "partial")
    assert first["cache_hit"] is False
    assert first["health_score"] is not None

    r = client.post(f"/api/v1/repos/{repo_id}/analyze", headers=auth)
    assert r.status_code == 200
    assert r.json()["cache_hit"] is True
    assert r.json()["id"] == first["id"]

    r = client.get(f"/api/v1/repos/{repo_id}/findings", headers=auth)
    assert r.status_code == 200
    rule_ids = {f["rule_id"] for f in r.json()}
    assert "py-eval-exec" in rule_ids
    # Ordered by priority desc.
    priorities = [f["priority_score"] for f in r.json()]
    assert priorities == sorted(priorities, reverse=True)

    r = client.get(f"/api/v1/repos/{repo_id}/files", headers=auth)
    assert r.status_code == 200
    assert r.json()[0]["path"] == "risky.py"
    assert set(r.json()[0]["risk_contributors"]) == {
        "complexity",
        "churn",
        "centrality",
        "security",
        "untested",
    }

    r = client.get(f"/api/v1/repos/{repo_id}/graph", headers=auth)
    assert r.status_code == 200
    edges = {(e["src"], e["dst"]) for e in r.json()["edges"]}
    assert ("helpers.py", "risky.py") in edges

    r = client.get(f"/api/v1/repos/{repo_id}/files/risky.py", headers=auth)
    assert r.status_code == 200
    assert "eval(" in r.json()["content"]

    assert client.get(f"/api/v1/repos/{repo_id}/files/nope.py", headers=auth).status_code == 404


def test_path_traversal_guard() -> None:
    from nexus.api.v1.repos import resolve_repo_path

    for bad in ("../secret", "..", "a/../../x", "/etc/passwd", "."):
        try:
            resolve_repo_path(bad)
        except ValueError:
            continue
        raise AssertionError(f"traversal accepted: {bad}")
    assert resolve_repo_path("src/a.py") == "src/a.py"
    assert resolve_repo_path("src/../src/a.py") == "src/a.py"


@pytest.mark.usefixtures("_fresh_db", "cloned")
def test_authz_isolation(client: TestClient) -> None:
    alice = {"Authorization": _login(client, "alice")}
    bob = {"Authorization": _login(client, "bob")}
    repo_id = client.post("/api/v1/repos", json={"owner": "o", "name": "r"}, headers=alice).json()[
        "id"
    ]
    assert client.get("/api/v1/repos", headers=bob).json() == []
    assert client.post(f"/api/v1/repos/{repo_id}/analyze", headers=bob).status_code == 404
    assert client.get(f"/api/v1/repos/{repo_id}/findings", headers=bob).status_code == 404


@pytest.mark.usefixtures("_fresh_db")
def test_dev_login_disabled_outside_dev(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    r = client.post("/api/v1/auth/dev-login", json={"login": "mallory"})
    assert r.status_code == 403


@pytest.mark.usefixtures("_fresh_db")
def test_invalid_repo_names_rejected(client: TestClient) -> None:
    auth = {"Authorization": _login(client, "alice")}
    assert (
        client.post("/api/v1/repos", json={"owner": "../x", "name": "r"}, headers=auth).status_code
        == 400
    )
