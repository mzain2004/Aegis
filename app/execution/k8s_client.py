"""Kubernetes API client initialization and lifecycle management.

Automatically detects whether it is running inside a cluster (via service
account) or locally (via ``~/.kube/config``). Never hardcodes credentials.

Security: credential material is handled exclusively by the official
``kubernetes`` client library. This module never reads, stores, logs, or
returns raw tokens, certificates, or passwords.
"""

from __future__ import annotations

from typing import Any

from app.execution.exceptions import (
    ExecutionUnavailable,
    KubernetesAuthenticationError,
)
from app.logger import get_logger

LOGGER = get_logger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency: the ``kubernetes`` package is not required for the
# existing HTTP-transport executor, so we import it lazily and degrade
# gracefully when it is absent.
# ---------------------------------------------------------------------------

try:
    from kubernetes import client as k8s_client  # type: ignore[import-untyped]
    from kubernetes import config as k8s_config  # type: ignore[import-untyped]
    from kubernetes.client.exceptions import (
        ApiException,  # type: ignore[import-untyped]
    )

    _K8S_AVAILABLE = True
except ImportError:
    k8s_client = None  # type: ignore[assignment]
    k8s_config = None  # type: ignore[assignment]
    ApiException = Exception  # type: ignore[misc, assignment]
    _K8S_AVAILABLE = False


def is_k8s_sdk_available() -> bool:
    """Return whether the ``kubernetes`` Python package is importable."""
    return _K8S_AVAILABLE


class KubernetesClientManager:
    """Initialize and manage a Kubernetes API client.

    Auto-detects the runtime environment:
    1. If running inside a pod, loads the in-cluster service-account config.
    2. Otherwise falls back to the local ``~/.kube/config``.

    All configuration is delegated to the official ``kubernetes`` library;
    no credentials are ever handled directly by Aegis.
    """

    def __init__(
        self,
        *,
        kubeconfig_path: str | None = None,
        context: str | None = None,
    ) -> None:
        self._kubeconfig_path = kubeconfig_path
        self._context = context
        self._api_client: Any | None = None
        self._core_v1: Any | None = None
        self._apps_v1: Any | None = None
        self._initialized = False

    # -- lifecycle ----------------------------------------------------------

    def initialize(self) -> None:
        """Load cluster credentials and instantiate typed API objects.

        Raises:
            ExecutionUnavailable: if the ``kubernetes`` SDK is not installed.
            KubernetesAuthenticationError: if cluster authentication fails.
        """
        if not _K8S_AVAILABLE:
            raise ExecutionUnavailable(
                "kubernetes Python SDK is not installed",
                backend="kubernetes",
            )

        try:
            try:
                k8s_config.load_incluster_config()
                LOGGER.info(
                    "k8s_client_initialized",
                    mode="in-cluster",
                )
            except k8s_config.ConfigException:
                k8s_config.load_kube_config(
                    config_file=self._kubeconfig_path,
                    context=self._context,
                )
                LOGGER.info(
                    "k8s_client_initialized",
                    mode="kubeconfig",
                    context=self._context or "default",
                )
        except Exception as exc:
            raise KubernetesAuthenticationError(
                f"failed to configure kubernetes client: {exc}",
            ) from exc

        self._api_client = k8s_client.ApiClient()
        self._core_v1 = k8s_client.CoreV1Api(self._api_client)
        self._apps_v1 = k8s_client.AppsV1Api(self._api_client)
        self._initialized = True

    def close(self) -> None:
        """Release the underlying API client resources."""
        if self._api_client is not None:
            try:
                self._api_client.close()
            except Exception:
                pass
            self._api_client = None
        self._core_v1 = None
        self._apps_v1 = None
        self._initialized = False

    # -- accessors ----------------------------------------------------------

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def core_v1(self) -> Any:
        """Return the ``CoreV1Api`` client."""
        if not self._initialized or self._core_v1 is None:
            raise ExecutionUnavailable(
                "kubernetes client not initialized",
                backend="kubernetes",
            )
        return self._core_v1

    @property
    def apps_v1(self) -> Any:
        """Return the ``AppsV1Api`` client."""
        if not self._initialized or self._apps_v1 is None:
            raise ExecutionUnavailable(
                "kubernetes client not initialized",
                backend="kubernetes",
            )
        return self._apps_v1
