from fastapi.testclient import TestClient

from app.api import health
from main import app


client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_db_returns_ok_when_database_is_reachable(monkeypatch):
    monkeypatch.setattr(health, "ping_database", lambda: True)

    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}
