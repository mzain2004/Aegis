# Aegis Monitoring Design

This document details the telemetry metrics design, thread-safe buffering, and percentiles statistics tracking for Aegis.

## Telemetry Collection Engine

Aegis implements a dual-mode telemetry collection model:

1. **Prometheus Engine**: Collects raw metrics using Prometheus client primitives (`Counter`, `Gauge`, `Histogram`).
2. **MonitoringService (In-Memory Collector)**: Tracks local statistics with thread-safe buffers. Exposes percentile statistics (Min, Max, Avg, P95, P99) dynamically.

## Latency Tracking Buffer

The `MonitoringService` maintains a bounded memory buffer of the last 1000 observations per latency metric. This enables low-overhead, real-time percentile computation without database lookups:

```python
# Bounded history buffer configuration
if metric_name not in self._observations:
    self._observations[metric_name] = []

history = self._observations[metric_name]
history.append(value)
if len(history) > 1000:
    history.pop(0)
```

## Percentile Math Calculations

Percentile values are computed using linear interpolation between closest ranks, ensuring precision across the history buffer:

```python
def percentile(p: float) -> float:
    k = (n - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)
```
- **P95 (95th Percentile)**: Represents the latency boundary that 95% of requests fall below. Useful for SLA compliance checks.
- **P99 (99th Percentile)**: Captures worst-case tail latencies (e.g., container scheduling delays).
