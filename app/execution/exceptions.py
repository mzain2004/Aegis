"""Execution-layer exceptions.

Provides a structured exception hierarchy for the Kubernetes execution backend.
Each exception carries machine-readable context so callers can build structured
error responses without parsing exception messages.

Security: exception messages never contain credentials, tokens, or secret
material. Callers that log exceptions must not attach request bodies that
may contain sensitive content.
"""

from __future__ import annotations

from typing import Any


class ExecutionError(Exception):
    """Base execution error.

    All execution-layer exceptions inherit from this class so callers can
    catch the entire category with a single handler.
    """

    def __init__(
        self,
        message: str = "execution error",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = details or {}


class ExecutionTimeout(ExecutionError):
    """Raised when execution exceeds the configured timeout."""

    def __init__(
        self,
        message: str = "execution timed out",
        *,
        timeout_seconds: int | float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra: dict[str, Any] = dict(details or {})
        if timeout_seconds is not None:
            extra["timeout_seconds"] = timeout_seconds
        super().__init__(message, details=extra)
        self.timeout_seconds = timeout_seconds


class ExecutionUnavailable(ExecutionError):
    """Raised when the execution backend is unreachable."""

    def __init__(
        self,
        message: str = "execution backend unavailable",
        *,
        backend: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra: dict[str, Any] = dict(details or {})
        if backend is not None:
            extra["backend"] = backend
        super().__init__(message, details=extra)
        self.backend = backend


class ExecutionRejected(ExecutionError):
    """Raised when the requested execution backend is not supported."""

    def __init__(
        self,
        message: str = "execution rejected",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)


# ---------------------------------------------------------------------------
# Kubernetes-specific exceptions
# ---------------------------------------------------------------------------


class KubernetesExecutionError(ExecutionError):
    """Base for all Kubernetes API execution failures."""

    def __init__(
        self,
        message: str = "kubernetes execution error",
        *,
        status_code: int | None = None,
        namespace: str | None = None,
        resource: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra: dict[str, Any] = dict(details or {})
        if status_code is not None:
            extra["k8s_status_code"] = status_code
        if namespace is not None:
            extra["namespace"] = namespace
        if resource is not None:
            extra["resource"] = resource
        super().__init__(message, details=extra)
        self.status_code = status_code
        self.namespace = namespace
        self.resource = resource


class InvalidRequestError(ExecutionError):
    """Raised when the request payload is malformed or missing required fields."""

    def __init__(
        self,
        message: str = "invalid execution request",
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra: dict[str, Any] = dict(details or {})
        if field is not None:
            extra["field"] = field
        super().__init__(message, details=extra)
        self.field = field


class UnsupportedOperationError(ExecutionError):
    """Raised when the requested operation is not in the supported set."""

    def __init__(
        self,
        message: str = "unsupported operation",
        *,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra: dict[str, Any] = dict(details or {})
        if operation is not None:
            extra["operation"] = operation
        super().__init__(message, details=extra)
        self.operation = operation


class KubernetesAuthenticationError(KubernetesExecutionError):
    """Raised when Kubernetes API authentication fails (HTTP 401)."""

    def __init__(
        self,
        message: str = "kubernetes authentication failed",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=401, details=details)


class KubernetesAuthorizationError(KubernetesExecutionError):
    """Raised when Kubernetes API authorization fails (HTTP 403)."""

    def __init__(
        self,
        message: str = "kubernetes authorization denied",
        *,
        namespace: str | None = None,
        resource: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=403,
            namespace=namespace,
            resource=resource,
            details=details,
        )


class NamespaceNotFoundError(KubernetesExecutionError):
    """Raised when the target namespace does not exist."""

    def __init__(
        self,
        message: str = "namespace not found",
        *,
        namespace: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=404,
            namespace=namespace,
            details=details,
        )


class ResourceNotFoundError(KubernetesExecutionError):
    """Raised when the target resource does not exist."""

    def __init__(
        self,
        message: str = "resource not found",
        *,
        namespace: str | None = None,
        resource: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=404,
            namespace=namespace,
            resource=resource,
            details=details,
        )


class ResourceConflictError(KubernetesExecutionError):
    """Raised when a write operation conflicts (HTTP 409)."""

    def __init__(
        self,
        message: str = "resource conflict",
        *,
        namespace: str | None = None,
        resource: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=409,
            namespace=namespace,
            resource=resource,
            details=details,
        )


class RetryableExecutionError(KubernetesExecutionError):
    """Raised for transient failures that may succeed on retry.

    Callers should check ``retry_after_seconds`` for server-suggested
    back-off durations.
    """

    def __init__(
        self,
        message: str = "retryable execution error",
        *,
        retry_after_seconds: int | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        extra: dict[str, Any] = dict(details or {})
        if retry_after_seconds is not None:
            extra["retry_after_seconds"] = retry_after_seconds
        super().__init__(message, status_code=status_code, details=extra)
        self.retry_after_seconds = retry_after_seconds
