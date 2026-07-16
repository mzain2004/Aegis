"""Tests for the TraceMiddleware and Correlation ID propagation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_correlation_id_generated_automatically() -> None:
    """Verify that a unique correlation ID is generated if not
    provided in the headers."""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert "X-Correlation-ID" in response.headers
        correlation_id = response.headers["X-Correlation-ID"]
        assert len(correlation_id) > 0


def test_correlation_id_propagated_from_request() -> None:
    """Verify that a provided correlation ID is preserved and propagated."""
    test_id = "test-correlation-id-12345"
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Correlation-ID": test_id})
        assert response.status_code == 200
        assert response.headers["X-Correlation-ID"] == test_id
