"""Execution backend factory."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.execution.base import ExecutionEngine
from app.execution.exceptions import ExecutionRejected
from app.execution.failsafe_executor import FailsafeCorrelatingExecutor
from app.execution.kubernetes_executor import KubernetesExecutor


class ExecutionFactory:
    """Select the configured execution backend."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def create(self) -> ExecutionEngine:
        backend = self._settings.execution_backend.strip().lower()

        if backend == "kubernetes":
            return KubernetesExecutor(settings=self._settings)

        if backend == "failsafe":
            return FailsafeCorrelatingExecutor(
                self._create_delegate(),
                settings=self._settings,
            )

        raise ExecutionRejected(
            f"Unsupported execution backend: {self._settings.execution_backend}"
        )

    def _create_delegate(self) -> ExecutionEngine:
        """Build the transport executor the failsafe correlator wraps."""

        delegate_backend = self._settings.failsafe_delegate_backend.strip().lower()

        if delegate_backend == "kubernetes":
            return KubernetesExecutor(settings=self._settings)

        raise ExecutionRejected(
            "Unsupported failsafe delegate backend: "
            f"{self._settings.failsafe_delegate_backend}"
        )
