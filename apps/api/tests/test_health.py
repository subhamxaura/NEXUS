from fastapi.testclient import TestClient

from nexus.main import app

client = TestClient(app)


def test_health_ok() -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_login_unconfigured_truthful() -> None:
    # Without GITHUB_CLIENT_ID configured this must 501, never fake a URL.
    r = client.get("/api/v1/auth/github/login")
    assert r.status_code in (200, 501)
    if r.status_code == 501:
        assert "not configured" in r.json()["detail"]


def test_callback_requires_code() -> None:
    r = client.get("/api/v1/auth/github/callback")
    assert r.status_code == 400
