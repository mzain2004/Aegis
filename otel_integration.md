# Aegis OpenTelemetry Integration

Aegis is equipped with optional OpenTelemetry tracing instrumentation, supporting distributed trace propagation across the proxy pipeline.

## Settings Configuration

OpenTelemetry features are controlled using the following settings in `app/config.py`:
- `OTEL_ENABLED`: Set to `True` to load OpenTelemetry trace exporters and initialize tracer provider. Defaults to `False`.
- `ENABLE_TRACE`: Enables route span tracing inside TraceMiddleware. Defaults to `True`.

## Trace Middleware

The `TraceMiddleware` automatically hooks into incoming HTTP requests to create matching OpenTelemetry spans:

```python
with start_span("http_request", attributes=span_attrs):
    response = await call_next(request)
```

## Graceful Fallback Mechanics

Aegis implements an import-safety block when OpenTelemetry dependencies are not installed in the target host:

```python
OTEL_AVAILABLE = False
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    # ...
    OTEL_AVAILABLE = True
except ImportError:
    trace = None
```

If `OTEL_ENABLED` is `True` but packages are missing, the service logs a warning and automatically falls back to a safe, no-op context manager:

```python
@contextlib.contextmanager
def start_span(span_name: str, attributes: dict[str, Any] | None = None):
    # If OTel is not active, yield None and do nothing
    yield None
```
This ensures zero runtime exceptions or service interruptions during production deployment.
