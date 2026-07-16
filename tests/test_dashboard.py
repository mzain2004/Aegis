"""Tests for the dashboard summary endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.monitoring.metrics import monitoring_service


def test_dashboard_summary_returns_aggregated_metrics() -> None:
    """Verify that the /dashboard/summary endpoint correctly reports
    statistics and system health status."""
    # Reset local service metrics
    monitoring_service.reset()

    # Seed mock metrics for calculation testing
    monitoring_service.increment(
        "proxy_requests_total", 10.0, labels={"method": "POST", "route": "/"}
    )
    monitoring_service.increment(
        "authentication_failure", 2.0, labels={"reason": "invalid_key"}
    )

    with TestClient(app) as client:
        response = client.get("/dashboard/summary")
        assert response.status_code == 200
        data = response.json()

        # Verify returned summary statistics match seeded metrics
        assert "pending_requests" in data
        assert "completed_today" in data
        assert "failed_today" in data
        assert "execution_success_rate" in data
        assert "average_latency" in data
        assert data["authentication_failures"] == 2
        assert data["uptime"] >= 0.0
        assert data["system_health"] == "healthy"
