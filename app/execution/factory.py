"""Execution backend factory."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.execution.exceptions import ExecutionRejected
from app.execution.kubernetes_executor import KubernetesExecutor
from app.execution.base import ExecutionEngine


class ExecutionFactory:
    """Select the configured execution backend."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def create(self) -> ExecutionEngine:
        backend = self._settings.execution_backend.strip().lower()

        if backend == "kubernetes":
            return KubernetesExecutor(settings=self._settings)

        raise ExecutionRejected(f"Unsupported execution backend: {self._settings.execution_backend}")