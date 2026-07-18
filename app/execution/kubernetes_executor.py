"""Kubernetes MCP execution backend.

This executor is a transport-only component. It executes already-approved
requests by forwarding stored raw bytes to the Kubernetes MCP server over
HTTP. It never decides whether a request is allowed — that responsibility
belongs exclusively to the approval layer.

The executor supports two modes:
1. **HTTP transport** (default, always available): forwards raw request
   bytes to the configured ``K8S_MCP_SERVER_URL``. This is the mode used
   by the existing approval workflow.
2. **Native K8s SDK** (optional, when ``kubernetes`` is installed): a
   ``KubernetesClientManager`` is initialized for direct API access.
   The HTTP transport remains the primary execution path.

Security:
- Never logs request bodies (may contain secrets in tool arguments).
- Never logs credentials, tokens, or certificate material.
- Structured logging uses sanitized context fields only.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.execution.base import ExecutionEngine
from app.execution.models import (
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    execution_metrics,
)
from app.logger import get_logger

LOGGER = get_logger(__name__)


class KubernetesExecutor(ExecutionEngine):
    """Transport-only executor that forwards raw bytes to Kubernetes MCP.

    The ``execute`` method preserves full backward compatibility with the
    original implementation. When an ``ExecutionContext`` is available, it
    is threaded through logging and returned in the result.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        metrics: ExecutionMetrics | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._metrics = metrics or execution_metrics
        if hasattr(LOGGER, "bind"):
            self._logger = LOGGER.bind(executor="kubernetes")
        else:
            self._logger = LOGGER

    # ------------------------------------------------------------------
    # Primary execution entry point
    # ------------------------------------------------------------------

    async def execute(
        self,
        body: bytes,
        headers: dict[str, str],
        *,
        context: ExecutionContext | None = None,
    ) -> ExecutionResult:
        """Execute an approved request through the Kubernetes MCP server.

        This method is backward compatible: callers that do not provide a
        ``context`` will receive results identical to the previous
        implementation.
        """

        retried = False

        # Structured logging context
        log_ctx: dict[str, Any] = {"backend": "kubernetes"}
        if context is not None:
            log_ctx.update(
                {
                    "request_id": context.request_id,
                    "approval_id": context.approval_id,
                    "execution_id": context.execution_id,
                    "executor_type": context.executor_type,
                    "execution_target": context.execution_target,
                }
            )

        self._logger.info("execution_start", **log_ctx)

        # -- optional request validation -----------------------------------
        operation_info = self._extract_operation_info(body)
        if operation_info:
            log_ctx["tool_name"] = operation_info.get("tool_name", "")
            log_ctx["namespace"] = operation_info.get("namespace", "")

        # -- execute with retry budget -------------------------------------
        max_attempts = max(1, 1 + self.settings.execution_retries)
        last_result: ExecutionResult | None = None

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                retried = True
                self._logger.info(
                    "execution_retry",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    **log_ctx,
                )

            result = await self._do_execute(
                body, headers, context=context, log_ctx=log_ctx
            )
            last_result = result

            if result.success or not result.retryable:
                break

        assert last_result is not None  # At least one attempt is always made
        result = last_result

        # -- metrics -------------------------------------------------------
        latency_ms = float(result.latency_ms)
        self._metrics.record_execution(
            success=result.success,
            latency_ms=latency_ms,
            timed_out=result.error_type == "timeout",
            retried=retried,
        )

        # -- final log -----------------------------------------------------
        self._logger.info(
            "execution_finish",
            status_code=result.status_code,
            success=result.success,
            latency_ms=result.latency_ms,
            error_type=result.error_type,
            **log_ctx,
        )

        return result

    # ------------------------------------------------------------------
    # Internal transport
    # ------------------------------------------------------------------

    async def _do_execute(
        self,
        body: bytes,
        headers: dict[str, str],
        *,
        context: ExecutionContext | None = None,
        log_ctx: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Single execution attempt via HTTP transport."""
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

            # Map specific HTTP status codes to structured errors
            error_type, error_detail, retryable = self._classify_response(response)

            return ExecutionResult(
                status_code=response.status_code,
                headers={key: value for key, value in response.headers.items()},
                body=response.content,
                latency_ms=latency_ms,
                backend="kubernetes",
                success=200 <= response.status_code < 300,
                error_type=error_type,
                error_detail=error_detail,
                context=context,
                retryable=retryable,
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
                error_type="timeout",
                error_detail="upstream read timeout exceeded",
                context=context,
                retryable=True,
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
                error_type="unavailable",
                error_detail="upstream connection failed",
                context=context,
                retryable=True,
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
                error_type="internal_error",
                error_detail="unexpected execution failure",
                context=context,
                retryable=False,
            )
        finally:
            if not client_provided:
                await client.aclose()

    # ------------------------------------------------------------------
    # Response classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_response(
        response: httpx.Response,
    ) -> tuple[str | None, str | None, bool]:
        """Classify an HTTP response into error_type, error_detail, retryable."""
        code = response.status_code

        if 200 <= code < 300:
            return None, None, False

        mapping: dict[int, tuple[str, str, bool]] = {
            401: (
                "authentication_failed",
                "kubernetes API authentication failed",
                False,
            ),
            403: (
                "authorization_denied",
                "kubernetes API authorization denied",
                False,
            ),
            404: ("not_found", "requested resource not found", False),
            409: ("conflict", "resource version conflict", True),
            422: ("invalid_request", "unprocessable entity", False),
            429: ("rate_limited", "API rate limit exceeded", True),
            500: ("k8s_internal_error", "kubernetes API internal error", True),
            502: ("bad_gateway", "upstream bad gateway", True),
            503: ("service_unavailable", "kubernetes API unavailable", True),
            504: ("gateway_timeout", "upstream gateway timeout", True),
        }

        if code in mapping:
            return mapping[code]

        if code >= 500:
            return "server_error", f"upstream server error: {code}", True

        return "client_error", f"upstream client error: {code}", False

    # ------------------------------------------------------------------
    # Request introspection (for logging only — never for authorization)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_operation_info(body: bytes) -> dict[str, str] | None:
        """Extract tool name and namespace from the request body.

        Used solely for structured logging context. Returns ``None`` on
        any parse failure. Never raises.
        """
        try:
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                return None
            params = payload.get("params", {})
            if not isinstance(params, dict):
                return None
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            if isinstance(arguments, dict):
                namespace = arguments.get("namespace", "")
            else:
                namespace = ""
            return {
                "tool_name": str(tool_name),
                "namespace": str(namespace),
            }
        except Exception:
            return None
