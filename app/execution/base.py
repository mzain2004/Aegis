"""Abstract execution engine interface.

Defines the contract that all execution backends must implement. The
interface is intentionally narrow: an executor receives approved raw
bytes, optional headers, and an optional context, then returns a result.

The executor must never make authorization decisions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.execution.models import ExecutionContext, ExecutionResult


class ExecutionEngine(ABC):
    """Abstract release interface for approved suspended requests."""

    @abstractmethod
    async def execute(
        self,
        body: bytes,
        headers: dict[str, str],
        *,
        context: ExecutionContext | None = None,
    ) -> ExecutionResult:
        """Execute the stored request body through the configured backend.

        Args:
            body: Raw request bytes exactly as stored during suspension.
            headers: HTTP headers captured from the original request.
            context: Optional immutable execution context for tracing,
                logging, and metrics. Callers that omit this will still
                receive a valid result — context is additive.

        Returns:
            An ``ExecutionResult`` describing the outcome.
        """
