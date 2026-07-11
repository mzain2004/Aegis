"""Health check tests for the Aegis proxy skeleton.

TODO: add broader API coverage when the proxy endpoints gain real behavior.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_healthy_status() -> None:
    """Verify the health endpoint responds with a success payload."""

    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
