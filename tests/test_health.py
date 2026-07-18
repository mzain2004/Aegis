"""Tests for the ready, live, health, and metrics endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_healthy_status() -> None:
    """Verify the health endpoint responds with a success status payload."""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


def test_live_endpoint_returns_healthy_status() -> None:
    """Verify the live endpoint responds with a success status payload."""
    with TestClient(app) as client:
        response = client.get("/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"


def test_ready_endpoint_returns_subsystem_status() -> None:
    """Verify the ready endpoint responds with structured subsystem status."""
    with TestClient(app) as client:
        response = client.get("/ready")
        print("DEBUG READY STATUS:", response.status_code, response.text)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "checks" in data
        assert data["checks"]["database"] is True
