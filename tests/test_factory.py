from __future__ import annotations

import pytest

from app.config import get_settings
from app.execution.exceptions import ExecutionRejected
from app.execution.factory import ExecutionFactory
from app.execution.failsafe_executor import FailsafeCorrelatingExecutor
from app.execution.kubernetes_executor import KubernetesExecutor


def test_factory_returns_kubernetes_executor() -> None:
    settings = get_settings().model_copy(update={"execution_backend": "kubernetes"})

    engine = ExecutionFactory(settings=settings).create()

    assert isinstance(engine, KubernetesExecutor)


def test_factory_rejects_unknown_backend() -> None:
    settings = get_settings().model_copy(update={"execution_backend": "aws"})

    with pytest.raises(ExecutionRejected):
        ExecutionFactory(settings=settings).create()


def test_factory_returns_failsafe_executor_gated_by_config() -> None:
    settings = get_settings().model_copy(
        update={
            "execution_backend": "failsafe",
            "failsafe_delegate_backend": "kubernetes",
        }
    )

    engine = ExecutionFactory(settings=settings).create()

    assert isinstance(engine, FailsafeCorrelatingExecutor)


def test_factory_rejects_unknown_failsafe_delegate() -> None:
    settings = get_settings().model_copy(
        update={
            "execution_backend": "failsafe",
            "failsafe_delegate_backend": "aws",
        }
    )

    with pytest.raises(ExecutionRejected):
        ExecutionFactory(settings=settings).create()
