"""Root endpoint tests for Phase 1 Veto Ops proxy."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_root_returns_service_metadata() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    json = response.json()
    assert json["service"] == "Veto Ops Proxy"
    assert json["version"] == "0.1.0"
    assert json["status"] == "running"
