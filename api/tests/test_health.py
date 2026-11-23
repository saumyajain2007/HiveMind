from fastapi.testclient import TestClient

from marketsim_api.main import app


def test_health_ok() -> None:
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["engine_version"]
