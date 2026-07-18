"""Tests for Prometheus metrics and the MonitoringService."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.monitoring.metrics import monitoring_service


def test_monitoring_service_operations() -> None:
    """Test custom metrics counting, gauging, and observations."""
    monitoring_service.reset()

    # Increment counter
    monitoring_service.increment(
        "proxy_requests_total", value=1, labels={"method": "POST", "route": "/"}
    )
    monitoring_service.increment(
        "proxy_requests_total", value=2, labels={"method": "POST", "route": "/"}
    )

    # Observe histogram/observations
    monitoring_service.observe("execution_latency", 10.0)
    monitoring_service.observe("execution_latency", 20.0)
    monitoring_service.observe("execution_latency", 30.0)

    # Verify snapshot
    snapshot = monitoring_service.snapshot()
    assert snapshot["proxy_requests_total"] == 3.0
    assert snapshot["execution_latency_count"] == 3.0
    assert snapshot["execution_latency_sum"] == 60.0
    assert snapshot["execution_latency_min"] == 10.0
    assert snapshot["execution_latency_max"] == 30.0

    # Test percentiles math
    percentiles = monitoring_service.get_percentiles("execution_latency")
    assert percentiles["min"] == 10.0
    assert percentiles["max"] == 30.0
    assert percentiles["average"] == 20.0
    assert percentiles["p95"] > 20.0
    assert percentiles["p99"] > 20.0


def test_metrics_endpoint_returns_prometheus_format() -> None:
    """Test that the /metrics endpoint serves valid Prometheus metrics."""
    with TestClient(app) as client:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "proxy_requests_total" in response.text
        assert "active_pending_requests" in response.text
