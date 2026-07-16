"""Execution result and context models.

Provides the immutable execution context that flows through the pipeline
and the result model returned by every executor.

Security: ``ExecutionContext`` must never store raw credentials, tokens,
or secret material. The ``request_fingerprint`` is a content hash — not
the request body itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Execution status
# ---------------------------------------------------------------------------


class ExecutionStatus(StrEnum):
    """Terminal status of an execution attempt."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Immutable execution context (Phase 4)
# ---------------------------------------------------------------------------


class ExecutionContext(BaseModel):
    """Immutable context that accompanies every execution pipeline invocation.

    Created once before execution begins and threaded through logging,
    metrics, and error handling without mutation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(description="Original MCP request identifier.")
    approval_id: str = Field(description="Nonce that authorized this execution.")
    execution_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this execution attempt.",
    )
    execution_time: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when execution was initiated.",
    )
    operator: str = Field(
        default="system",
        description="Identity of the operator who approved the request.",
    )
    request_fingerprint: str = Field(
        description="SHA-256 hash of the original request body.",
    )
    executor_type: str = Field(
        default="kubernetes",
        description="Name of the execution backend.",
    )
    execution_target: str = Field(
        default="",
        description="Target MCP tool name or operation.",
    )
    status: ExecutionStatus = Field(
        default=ExecutionStatus.PENDING,
        description="Current execution status.",
    )


# ---------------------------------------------------------------------------
# Execution result (preserved from Phase 6)
# ---------------------------------------------------------------------------


class ExecutionResult(BaseModel):
    """Structured result returned by a backend executor."""

    model_config = ConfigDict(extra="forbid")

    status_code: int = Field(description="HTTP status code from execution.")
    headers: dict[str, str] = Field(description="Response headers from upstream.")
    body: bytes = Field(description="Raw upstream response body.")
    latency_ms: int = Field(description="End-to-end execution latency in ms.")
    backend: str = Field(description="Execution backend name.")
    success: bool = Field(description="Whether execution completed successfully.")
    error_type: str | None = Field(
        default=None,
        description="Machine-readable error category when success is False.",
    )
    error_detail: str | None = Field(
        default=None,
        description="Human-readable error message when success is False.",
    )
    context: ExecutionContext | None = Field(
        default=None,
        description="Execution context when available.",
    )
    retryable: bool = Field(
        default=False,
        description="Whether the failure is transient and may succeed on retry.",
    )


# ---------------------------------------------------------------------------
# Structured error response
# ---------------------------------------------------------------------------


class ExecutionErrorResponse(BaseModel):
    """Wire-format error returned to callers on execution failure."""

    model_config = ConfigDict(extra="forbid")

    error: str = Field(description="Machine-readable error code.")
    message: str = Field(description="Human-readable description.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured context.",
    )
    retryable: bool = Field(
        default=False,
        description="Whether the caller should retry.",
    )
    execution_id: str | None = Field(
        default=None,
        description="Execution ID for correlation.",
    )


# ---------------------------------------------------------------------------
# Execution metrics collection point (Phase 7)
# ---------------------------------------------------------------------------


class ExecutionMetrics:
    """Thread-safe, in-memory execution metrics collector.

    Designed so a stream or bridge can read counters and latency profiles
    for the complete human approval and execution pipeline.
    """

    def __init__(self) -> None:
        self._total: int = 0
        self._success: int = 0
        self._failure: int = 0
        self._timeout: int = 0
        self._latency_sum_ms: float = 0.0
        self._latency_max_ms: float = 0.0
        self._retries: int = 0

        # Pipeline metrics
        self._pending_requests: int = 0
        self._approved_requests: int = 0
        self._rejected_requests: int = 0
        self._expired_requests: int = 0
        self._approval_latency_sum: float = 0.0
        self._approval_latency_max: float = 0.0
        self._execution_latency_sum: float = 0.0
        self._execution_latency_max: float = 0.0
        self._execution_total: int = 0
        self._execution_success: int = 0
        self._execution_failure: int = 0

        import threading

        self._lock = threading.Lock()

    # -- recording ----------------------------------------------------------

    def record_pending(self) -> None:
        with self._lock:
            self._pending_requests += 1

    def record_approved(self) -> None:
        with self._lock:
            self._approved_requests += 1

    def record_rejected(self) -> None:
        with self._lock:
            self._rejected_requests += 1

    def record_expired(self) -> None:
        with self._lock:
            self._expired_requests += 1

    def record_approval_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._approval_latency_sum += latency_ms
            if latency_ms > self._approval_latency_max:
                self._approval_latency_max = latency_ms

    def record_execution_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._execution_latency_sum += latency_ms
            if latency_ms > self._execution_latency_max:
                self._execution_latency_max = latency_ms

    def record_execution(
        self,
        *,
        success: bool,
        latency_ms: float,
        timed_out: bool = False,
        retried: bool = False,
    ) -> None:
        with self._lock:
            self._total += 1
            self._execution_total += 1
            if success:
                self._success += 1
                self._execution_success += 1
            else:
                self._failure += 1
                self._execution_failure += 1
            if timed_out:
                self._timeout += 1
            if retried:
                self._retries += 1
            self._latency_sum_ms += latency_ms
            if latency_ms > self._latency_max_ms:
                self._latency_max_ms = latency_ms
            # Also record execution latency
            self._execution_latency_sum += latency_ms
            if latency_ms > self._execution_latency_max:
                self._execution_latency_max = latency_ms

    # -- snapshot -----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a point-in-time copy of all tracked metrics."""
        with self._lock:
            avg = self._latency_sum_ms / self._total if self._total else 0.0
            avg_approval = (
                self._approval_latency_sum / self._approved_requests
                if self._approved_requests
                else 0.0
            )
            avg_execution = (
                self._execution_latency_sum / self._execution_total
                if self._execution_total
                else 0.0
            )
            return {
                "execution_total": self._total,
                "execution_success": self._success,
                "execution_failure": self._failure,
                "execution_timeout": self._timeout,
                "execution_retries": self._retries,
                "latency_avg_ms": round(avg, 2),
                "latency_max_ms": round(self._latency_max_ms, 2),
                # Pipeline specific
                "pending_requests": self._pending_requests,
                "approved_requests": self._approved_requests,
                "rejected_requests": self._rejected_requests,
                "expired_requests": self._expired_requests,
                "execution_success_count": self._execution_success,
                "execution_failure_count": self._execution_failure,
                "approval_latency_avg_ms": round(avg_approval, 2),
                "approval_latency_max_ms": round(self._approval_latency_max, 2),
                "execution_latency_avg_ms": round(avg_execution, 2),
                "execution_latency_max_ms": round(self._execution_latency_max, 2),
            }

    def reset(self) -> None:
        """Reset all counters. Primarily for testing."""
        with self._lock:
            self._total = 0
            self._success = 0
            self._failure = 0
            self._timeout = 0
            self._latency_sum_ms = 0.0
            self._latency_max_ms = 0.0
            self._retries = 0
            self._pending_requests = 0
            self._approved_requests = 0
            self._rejected_requests = 0
            self._expired_requests = 0
            self._approval_latency_sum = 0.0
            self._approval_latency_max = 0.0
            self._execution_latency_sum = 0.0
            self._execution_latency_max = 0.0
            self._execution_total = 0
            self._execution_success = 0
            self._execution_failure = 0


# Module-level singleton metrics collector
execution_metrics = ExecutionMetrics()
