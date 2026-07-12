"""Route tests for proxy and approval flow."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_proxy_returns_501() -> None:
    response = client.post("/")
    # In Phase 2 the proxy attempts to forward to the configured MCP server.
    # With no downstream available in the test environment this will return 503.
    assert response.status_code == 503


def test_approve_returns_501() -> None:
    response = client.post("/approve")
    assert response.status_code == 400
    assert response.json() == {"message": "nonce is required"}
