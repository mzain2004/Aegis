"""OpenTelemetry tracing, Correlation ID management, and TraceMiddleware for Aegis."""

from __future__ import annotations

import contextlib
import contextvars
import time
import uuid
from collections.abc import Generator
from typing import Any

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

LOGGER = structlog.get_logger(__name__)

# Correlation ID Context Variable
correlation_id_ctx = contextvars.ContextVar("correlation_id", default="")

# Try importing OpenTelemetry components
OTEL_AVAILABLE = False
try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    OTEL_AVAILABLE = True
except ImportError:
    trace = None  # type: ignore
    TracerProvider = None  # type: ignore
    BatchSpanProcessor = None  # type: ignore
    OTLPSpanExporter = None  # type: ignore

# Global Tracer
_tracer: Any = None


def init_tracer() -> None:
    """Initialize OpenTelemetry tracer if enabled in configuration."""
    global _tracer
    settings = get_settings()

    if not settings.otel_enabled:
        _tracer = None
        return

    if not OTEL_AVAILABLE:
        LOGGER.warning(
            "otel_enabled_but_dependencies_missing",
            reason="opentelemetry libraries not installed",
        )
        _tracer = None
        return

    try:
        provider = TracerProvider()
        # Export spans via OTLP gRPC/HTTP exporter
        otlp_exporter = OTLPSpanExporter()
        processor = BatchSpanProcessor(otlp_exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("aegis")
        LOGGER.info("otel_tracer_initialized_successfully")
    except Exception as e:
        LOGGER.warning("otel_tracer_initialization_failed", error=str(e))
        _tracer = None


@contextlib.contextmanager
def start_span(
    span_name: str, attributes: dict[str, Any] | None = None
) -> Generator[Any, None, None]:
    """Start an OpenTelemetry span if OTEL is enabled, or act as a
    no-op context manager."""
    global _tracer
    settings = get_settings()

    # Initialize tracer on first call if otel is enabled and tracer not set
    if settings.otel_enabled and _tracer is None:
        init_tracer()

    if _tracer is not None:
        # OTEL is active
        with _tracer.start_as_current_span(span_name) as span:
            if attributes:
                for k, v in attributes.items():
                    if v is not None:
                        span.set_attribute(k, v)
            yield span
    else:
        # Graceful no-op fallback
        yield None


class TraceMiddleware(BaseHTTPMiddleware):
    """FastAPI Middleware to track requests, generate/propagate Correlation
    IDs, and record metrics."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        start_time = time.monotonic()
        settings = get_settings()

        # 1. Resolve and bind Correlation ID
        correlation_id = request.headers.get("x-correlation-id")
        if not correlation_id:
            correlation_id = request.headers.get("X-Correlation-ID")
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # Clear and bind in structlog contextvars
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        # 2. Match route details
        route_path = request.scope.get("route")
        if route_path and hasattr(route_path, "path"):
            route = route_path.path
        else:
            route = request.url.path

        method = request.method

        # 3. Track request metrics (if enabled)
        if settings.metrics_enabled:
            from app.monitoring.metrics import monitoring_service

            monitoring_service.increment(
                "proxy_requests_total", labels={"method": method, "route": route}
            )

        status_code = 500
        outcome = "failure"
        exception_name = None

        try:
            # 4. Execute request inside tracing span
            span_attrs = {
                "http.method": method,
                "http.route": route,
                "correlation_id": correlation_id,
            }
            with start_span("http_request", attributes=span_attrs):
                response = await call_next(request)

            status_code = response.status_code
            if 200 <= status_code < 400:
                outcome = "success"
            else:
                outcome = "error"

            # Propagate correlation ID in response header
            response.headers["X-Correlation-ID"] = correlation_id
            return response  # type: ignore[no-any-return]

        except Exception as e:
            exception_name = e.__class__.__name__
            outcome = "exception"
            raise e

        finally:
            duration = time.monotonic() - start_time

            # Log structured trace detail
            # Logging fields matching requirements:
            # Correlation ID, Operator, Latency, Outcome
            log_fields = {
                "correlation_id": correlation_id,
                "route": route,
                "method": method,
                "status_code": status_code,
                "latency_sec": duration,
                "outcome": outcome,
            }
            if exception_name:
                log_fields["exception"] = exception_name

            # Check if operator was bound during authentication dependency
            op_username = structlog.contextvars.get_contextvars().get(
                "operator_username"
            )
            if op_username:
                log_fields["operator"] = op_username

            LOGGER.info("Request processed", **log_fields)

            # Record execution latency to MonitoringService if applicable
            if settings.metrics_enabled:
                from app.monitoring.metrics import monitoring_service

                monitoring_service.observe("execution_duration_seconds", duration)
