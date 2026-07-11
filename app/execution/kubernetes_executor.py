"""Kubernetes MCP execution backend."""

from __future__ import annotations

import time

import httpx

from app.config import Settings, get_settings
from app.execution.base import ExecutionEngine
from app.execution.models import ExecutionResult


class KubernetesExecutor(ExecutionEngine):
    """Transport-only executor that forwards raw bytes to Kubernetes MCP."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    async def execute(
        self,
        body: bytes,
        headers: dict[str, str],
    ) -> ExecutionResult:
        start = time.monotonic()
        client_provided = self._client is not None
        client = self._client or httpx.AsyncClient()
        timeout = httpx.Timeout(self.settings.execution_timeout_seconds)

        try:
            response = await client.post(
                self.settings.k8s_mcp_server_url,
                content=body,
                headers=headers,
                timeout=timeout,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            return ExecutionResult(
                status_code=response.status_code,
                headers={key: value for key, value in response.headers.items()},
                body=response.content,
                latency_ms=latency_ms,
                backend="kubernetes",
                success=200 <= response.status_code < 300,
            )
        except httpx.ReadTimeout:
            latency_ms = int((time.monotonic() - start) * 1000)
            return ExecutionResult(
                status_code=504,
                headers={},
                body=b"",
                latency_ms=latency_ms,
                backend="kubernetes",
                success=False,
            )
        except httpx.ConnectError:
            latency_ms = int((time.monotonic() - start) * 1000)
            return ExecutionResult(
                status_code=503,
                headers={},
                body=b"",
                latency_ms=latency_ms,
                backend="kubernetes",
                success=False,
            )
        except Exception:
            latency_ms = int((time.monotonic() - start) * 1000)
            return ExecutionResult(
                status_code=500,
                headers={},
                body=b"",
                latency_ms=latency_ms,
                backend="kubernetes",
                success=False,
            )
        finally:
            if not client_provided:
                await client.aclose()
