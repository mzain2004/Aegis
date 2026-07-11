"""Execution-layer exceptions."""

from __future__ import annotations


class ExecutionError(Exception):
    """Base execution error."""


class ExecutionTimeout(ExecutionError):
    """Raised when execution exceeds the configured timeout."""


class ExecutionUnavailable(ExecutionError):
    """Raised when the execution backend is unreachable."""


class ExecutionRejected(ExecutionError):
    """Raised when the requested execution backend is not supported."""
