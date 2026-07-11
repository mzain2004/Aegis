"""Abstract execution engine interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.execution.models import ExecutionResult


class ExecutionEngine(ABC):
    """Abstract release interface for approved suspended requests."""

    @abstractmethod
    async def execute(
        self,
        body: bytes,
        headers: dict[str, str],
    ) -> ExecutionResult:
        """Execute the stored request body through the configured backend."""
