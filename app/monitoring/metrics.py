"""Prometheus metrics definition and MonitoringService implementation for Aegis."""

from __future__ import annotations

import math
import threading
import time
from typing import Any

from prometheus_client import REGISTRY, Counter, Gauge, Histogram

# Thread-safe lock for dynamic registry checks
_METRICS_LOCK = threading.Lock()
_START_TIME = time.time()


def _get_or_create_metric(
    metric_type: type, name: str, documentation: str, labelnames: tuple[str, ...] = ()
) -> Any:
    """Helper to safely retrieve an existing metric from the Prometheus
    registry or register it."""
    with _METRICS_LOCK:
        # Check standard prometheus collectors
        for collector in list(REGISTRY._names_to_collectors.values()):
            if hasattr(collector, "_name") and collector._name == name:
                return collector
            if hasattr(collector, "_names") and name in collector._names:
                return collector

        return metric_type(name, documentation, labelnames=labelnames)


# 1. Prometheus Metric Declarations

# Request counters
proxy_requests_total = _get_or_create_metric(
    Counter,
    "proxy_requests_total",
    "Total proxy requests received",
    ("method", "route"),
)
proxy_requests_read = _get_or_create_metric(
    Counter, "proxy_requests_read", "Total read-only proxy requests"
)
proxy_requests_mutating = _get_or_create_metric(
    Counter, "proxy_requests_mutating", "Total mutating proxy requests"
)
proxy_requests_blocked = _get_or_create_metric(
    Counter, "proxy_requests_blocked", "Total blocked proxy requests"
)
proxy_requests_forwarded = _get_or_create_metric(
    Counter, "proxy_requests_forwarded", "Total forwarded proxy requests"
)

# Approval metrics
approvals_pending = _get_or_create_metric(
    Gauge, "approvals_pending", "Number of currently pending approvals"
)
approvals_completed = _get_or_create_metric(
    Counter, "approvals_completed", "Total completed approvals"
)
approvals_failed = _get_or_create_metric(
    Counter, "approvals_failed", "Total failed approvals"
)
approvals_expired = _get_or_create_metric(
    Counter, "approvals_expired", "Total expired approvals"
)
approvals_replayed = _get_or_create_metric(
    Counter, "approvals_replayed", "Total replayed approvals"
)
approvals_rejected = _get_or_create_metric(
    Counter, "approvals_rejected", "Total rejected approvals"
)

# Execution metrics
executions_total = _get_or_create_metric(
    Counter, "executions_total", "Total execution runs started"
)
executions_success = _get_or_create_metric(
    Counter, "executions_success", "Total successful execution runs"
)
executions_failure = _get_or_create_metric(
    Counter, "executions_failure", "Total failed execution runs"
)
executions_timeout = _get_or_create_metric(
    Counter, "executions_timeout", "Total timed-out execution runs"
)
execution_duration_seconds = _get_or_create_metric(
    Histogram, "execution_duration_seconds", "Duration of execution runs in seconds"
)

# Authentication metrics
authentication_success = _get_or_create_metric(
    Counter,
    "authentication_success",
    "Total successful operator authentications",
    ("username",),
)
authentication_failure = _get_or_create_metric(
    Counter,
    "authentication_failure",
    "Total failed operator authentications",
    ("reason",),
)
permission_denied = _get_or_create_metric(
    Counter,
    "permission_denied",
    "Total permission denial events",
    ("username", "permission"),
)

# Database metrics
db_queries_total = _get_or_create_metric(
    Counter, "db_queries_total", "Total database queries executed"
)
db_transaction_duration = _get_or_create_metric(
    Histogram, "db_transaction_duration", "Duration of database transactions in seconds"
)
db_pool_connections = _get_or_create_metric(
    Gauge, "db_pool_connections", "Number of active DB pool connections"
)

# System metrics
startup_timestamp = _get_or_create_metric(
    Gauge, "startup_timestamp", "System startup UNIX timestamp"
)
uptime_seconds = _get_or_create_metric(
    Gauge, "uptime_seconds", "System uptime in seconds"
)
active_pending_requests = _get_or_create_metric(
    Gauge, "active_pending_requests", "Active unexpired pending requests count"
)

# Initialize startup timestamp
startup_timestamp.set(_START_TIME)


class MonitoringService:
    """Thread-safe, unified service for metrics management and statistics snapshots."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._custom_stats: dict[str, float] = {}
        # Stores last 1000 observed values per metric name for percentile calculations
        self._observations: dict[str, list[float]] = {}

    def increment(
        self, metric_name: str, value: float = 1, labels: dict[str, str] | None = None
    ) -> None:
        """Increment a counter or gauge metric."""
        with self._lock:
            prom_metric = self._get_prom_metric(metric_name)
            if prom_metric:
                if labels:
                    prom_metric.labels(**labels).inc(value)
                else:
                    prom_metric.inc(value)

            self._custom_stats[metric_name] = (
                self._custom_stats.get(metric_name, 0.0) + value
            )

    def observe(
        self, metric_name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """Observe a histogram value."""
        with self._lock:
            prom_metric = self._get_prom_metric(metric_name)
            if prom_metric:
                if labels:
                    prom_metric.labels(**labels).observe(value)
                else:
                    prom_metric.observe(value)

            # Maintain observation history (max 1000 items)
            if metric_name not in self._observations:
                self._observations[metric_name] = []

            history = self._observations[metric_name]
            history.append(value)
            if len(history) > 1000:
                history.pop(0)

            # Update standard min/max/average stats locally
            cache_key_min = f"{metric_name}_min"
            cache_key_max = f"{metric_name}_max"
            cache_key_sum = f"{metric_name}_sum"
            cache_key_count = f"{metric_name}_count"

            self._custom_stats[cache_key_count] = (
                self._custom_stats.get(cache_key_count, 0.0) + 1
            )
            self._custom_stats[cache_key_sum] = (
                self._custom_stats.get(cache_key_sum, 0.0) + value
            )

            current_min = self._custom_stats.get(cache_key_min, float("inf"))
            self._custom_stats[cache_key_min] = min(current_min, value)

            current_max = self._custom_stats.get(cache_key_max, float("-inf"))
            self._custom_stats[cache_key_max] = max(current_max, value)

    def gauge(
        self, metric_name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """Set a gauge value."""
        with self._lock:
            prom_metric = self._get_prom_metric(metric_name)
            if prom_metric:
                if labels:
                    prom_metric.labels(**labels).set(value)
                else:
                    prom_metric.set(value)

            self._custom_stats[metric_name] = value

    def get_percentiles(self, metric_name: str) -> dict[str, float]:
        """Compute min, max, average, p95, p99 for the given metric."""
        with self._lock:
            values = self._observations.get(metric_name, [])
            if not values:
                return {"min": 0.0, "max": 0.0, "average": 0.0, "p95": 0.0, "p99": 0.0}

            sorted_vals = sorted(values)
            n = len(sorted_vals)

            def percentile(p: float) -> float:
                k = (n - 1) * p
                f = math.floor(k)
                c = math.ceil(k)
                if f == c:
                    return sorted_vals[int(k)]
                return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)

            avg = sum(sorted_vals) / n
            return {
                "min": sorted_vals[0],
                "max": sorted_vals[-1],
                "average": avg,
                "p95": percentile(0.95),
                "p99": percentile(0.99),
            }

    def snapshot(self) -> dict[str, float]:
        """Return a thread-safe snapshot of all registered local and system metrics."""
        with self._lock:
            uptime = time.time() - _START_TIME
            uptime_seconds.set(uptime)
            self._custom_stats["uptime_seconds"] = uptime

            return dict(self._custom_stats)

    def reset(self) -> None:
        """Reset all locally tracked metrics and statistics."""
        with self._lock:
            self._custom_stats.clear()
            self._observations.clear()
            self._custom_stats["startup_timestamp"] = _START_TIME

    def _get_prom_metric(self, name: str) -> Any:
        """Maps standard metric names to global Prometheus metrics."""
        mapping = {
            "proxy_requests_total": proxy_requests_total,
            "proxy_requests_read": proxy_requests_read,
            "proxy_requests_mutating": proxy_requests_mutating,
            "proxy_requests_blocked": proxy_requests_blocked,
            "proxy_requests_forwarded": proxy_requests_forwarded,
            "approvals_pending": approvals_pending,
            "approvals_completed": approvals_completed,
            "approvals_failed": approvals_failed,
            "approvals_expired": approvals_expired,
            "approvals_replayed": approvals_replayed,
            "approvals_rejected": approvals_rejected,
            "executions_total": executions_total,
            "executions_success": executions_success,
            "executions_failure": executions_failure,
            "executions_timeout": executions_timeout,
            "execution_duration_seconds": execution_duration_seconds,
            "authentication_success": authentication_success,
            "authentication_failure": authentication_failure,
            "permission_denied": permission_denied,
            "db_queries_total": db_queries_total,
            "db_transaction_duration": db_transaction_duration,
            "db_pool_connections": db_pool_connections,
            "startup_timestamp": startup_timestamp,
            "uptime_seconds": uptime_seconds,
            "active_pending_requests": active_pending_requests,
        }
        return mapping.get(name)


# Global thread-safe MonitoringService instance
monitoring_service = MonitoringService()
