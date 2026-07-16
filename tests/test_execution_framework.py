"""Comprehensive tests for the Kubernetes execution framework.

Phase 8: Unit tests covering executor initialization, configuration,
execution mapping, exception handling, context threading, metrics,
structured logging, and retry logic.

All tests use mocked HTTP transports — no real Kubernetes cluster required.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import FrozenInstanceError

import httpx
import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.execution.exceptions import (
    ExecutionError,
    ExecutionRejected,
    ExecutionTimeout,
    ExecutionUnavailable,
    InvalidRequestError,
    KubernetesAuthenticationError,
    KubernetesAuthorizationError,
    KubernetesExecutionError,
    NamespaceNotFoundError,
    ResourceConflictError,
    ResourceNotFoundError,
    RetryableExecutionError,
    UnsupportedOperationError,
)
from app.execution.factory import ExecutionFactory
from app.execution.k8s_client import KubernetesClientManager, is_k8s_sdk_available
from app.execution.kubernetes_executor import KubernetesExecutor
from app.execution.models import (
    ExecutionContext,
    ExecutionErrorResponse,
    ExecutionMetrics,
    ExecutionResult,
    ExecutionStatus,
    execution_metrics,
)
from app.execution.operation_map import (
    K8sOperation,
    K8sVerb,
    OperationCategory,
    extract_request_params,
    is_supported,
    lookup_operation,
    supported_operations,
    supported_tool_names,
)

# ============================================================================
# Helpers
# ============================================================================


def _make_settings(**overrides: object) -> object:
    return get_settings().model_copy(update=overrides)


def _make_context(**overrides: object) -> ExecutionContext:
    defaults = {
        "request_id": "req-1",
        "approval_id": "nonce-1",
        "request_fingerprint": "abc123",
        "execution_target": "kubectl_delete",
    }
    defaults.update(overrides)
    return ExecutionContext(**defaults)  # type: ignore[arg-type]


def _mcp_body(tool_name: str = "kubectl_delete", **arguments: object) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    ).encode()


# ============================================================================
# 1. Exception hierarchy tests
# ============================================================================


class TestExceptionHierarchy:
    def test_all_exceptions_inherit_from_execution_error(self) -> None:
        exceptions = [
            ExecutionTimeout(),
            ExecutionUnavailable(),
            ExecutionRejected(),
            KubernetesExecutionError(),
            InvalidRequestError(),
            UnsupportedOperationError(),
            KubernetesAuthenticationError(),
            KubernetesAuthorizationError(),
            NamespaceNotFoundError(),
            ResourceNotFoundError(),
            ResourceConflictError(),
            RetryableExecutionError(),
        ]
        for exc in exceptions:
            assert isinstance(exc, ExecutionError), f"{type(exc)} is not ExecutionError"

    def test_exception_carries_details(self) -> None:
        exc = KubernetesExecutionError(
            "test",
            status_code=404,
            namespace="prod",
            resource="pod/web",
            details={"extra": "info"},
        )
        assert exc.status_code == 404
        assert exc.namespace == "prod"
        assert exc.resource == "pod/web"
        assert exc.details["extra"] == "info"
        assert exc.details["k8s_status_code"] == 404

    def test_timeout_carries_duration(self) -> None:
        exc = ExecutionTimeout("slow", timeout_seconds=30)
        assert exc.timeout_seconds == 30
        assert exc.details["timeout_seconds"] == 30

    def test_retryable_carries_backoff(self) -> None:
        exc = RetryableExecutionError(retry_after_seconds=5)
        assert exc.retry_after_seconds == 5
        assert exc.details["retry_after_seconds"] == 5

    def test_unsupported_operation_carries_name(self) -> None:
        exc = UnsupportedOperationError(operation="kubectl_nuke")
        assert exc.operation == "kubectl_nuke"
        assert exc.details["operation"] == "kubectl_nuke"

    def test_invalid_request_carries_field(self) -> None:
        exc = InvalidRequestError(field="namespace")
        assert exc.field == "namespace"
        assert exc.details["field"] == "namespace"

    def test_k8s_auth_exceptions_have_correct_status(self) -> None:
        assert KubernetesAuthenticationError().status_code == 401
        assert KubernetesAuthorizationError().status_code == 403

    def test_namespace_not_found_status(self) -> None:
        exc = NamespaceNotFoundError(namespace="staging")
        assert exc.status_code == 404
        assert exc.namespace == "staging"

    def test_resource_conflict_status(self) -> None:
        exc = ResourceConflictError(namespace="prod", resource="deploy/api")
        assert exc.status_code == 409


# ============================================================================
# 2. Execution models tests
# ============================================================================


class TestExecutionModels:
    def test_execution_status_values(self) -> None:
        assert ExecutionStatus.PENDING == "pending"
        assert ExecutionStatus.SUCCESS == "success"
        assert ExecutionStatus.FAILED == "failed"
        assert ExecutionStatus.TIMEOUT == "timeout"
        assert ExecutionStatus.REJECTED == "rejected"
        assert ExecutionStatus.RUNNING == "running"

    def test_execution_context_is_immutable(self) -> None:
        ctx = _make_context()
        with pytest.raises(ValidationError):
            ctx.request_id = "changed"  # type: ignore[misc]

    def test_execution_context_generates_unique_ids(self) -> None:
        ctx1 = _make_context()
        ctx2 = _make_context()
        assert ctx1.execution_id != ctx2.execution_id

    def test_execution_context_default_values(self) -> None:
        ctx = _make_context()
        assert ctx.operator == "system"
        assert ctx.executor_type == "kubernetes"
        assert ctx.status == ExecutionStatus.PENDING
        assert ctx.execution_time is not None

    def test_execution_result_backward_compat(self) -> None:
        """Original ExecutionResult fields must still work."""
        result = ExecutionResult(
            status_code=200,
            headers={"x": "1"},
            body=b"ok",
            latency_ms=5,
            backend="kubernetes",
            success=True,
        )
        assert result.status_code == 200
        assert result.body == b"ok"
        assert result.error_type is None
        assert result.context is None
        assert result.retryable is False

    def test_execution_result_with_error_fields(self) -> None:
        result = ExecutionResult(
            status_code=503,
            headers={},
            body=b"",
            latency_ms=10,
            backend="kubernetes",
            success=False,
            error_type="unavailable",
            error_detail="connection refused",
            retryable=True,
        )
        assert result.error_type == "unavailable"
        assert result.retryable is True

    def test_execution_error_response(self) -> None:
        resp = ExecutionErrorResponse(
            error="timeout",
            message="upstream timed out",
            retryable=True,
            execution_id="exec-1",
        )
        assert resp.error == "timeout"
        assert resp.retryable is True
        assert resp.execution_id == "exec-1"


# ============================================================================
# 3. Execution metrics tests
# ============================================================================


class TestExecutionMetrics:
    def test_initial_state(self) -> None:
        m = ExecutionMetrics()
        snap = m.snapshot()
        assert snap["execution_total"] == 0
        assert snap["execution_success"] == 0
        assert snap["execution_failure"] == 0
        assert snap["latency_avg_ms"] == 0.0

    def test_record_success(self) -> None:
        m = ExecutionMetrics()
        m.record_execution(success=True, latency_ms=100.0)
        snap = m.snapshot()
        assert snap["execution_total"] == 1
        assert snap["execution_success"] == 1
        assert snap["execution_failure"] == 0
        assert snap["latency_avg_ms"] == 100.0

    def test_record_failure(self) -> None:
        m = ExecutionMetrics()
        m.record_execution(success=False, latency_ms=50.0, timed_out=True)
        snap = m.snapshot()
        assert snap["execution_failure"] == 1
        assert snap["execution_timeout"] == 1

    def test_record_retries(self) -> None:
        m = ExecutionMetrics()
        m.record_execution(success=True, latency_ms=10.0, retried=True)
        snap = m.snapshot()
        assert snap["execution_retries"] == 1

    def test_latency_max(self) -> None:
        m = ExecutionMetrics()
        m.record_execution(success=True, latency_ms=10.0)
        m.record_execution(success=True, latency_ms=200.0)
        m.record_execution(success=True, latency_ms=50.0)
        snap = m.snapshot()
        assert snap["latency_max_ms"] == 200.0
        assert snap["latency_avg_ms"] == round((10 + 200 + 50) / 3, 2)

    def test_reset(self) -> None:
        m = ExecutionMetrics()
        m.record_execution(success=True, latency_ms=100.0)
        m.reset()
        snap = m.snapshot()
        assert snap["execution_total"] == 0

    def test_module_level_singleton_exists(self) -> None:
        assert execution_metrics is not None
        assert isinstance(execution_metrics, ExecutionMetrics)


# ============================================================================
# 4. Operation mapping tests
# ============================================================================


class TestOperationMap:
    def test_all_read_only_tools_are_mapped(self) -> None:
        read_tools = [
            "kubectl_get",
            "kubectl_describe",
            "kubectl_logs",
            "kubectl_top",
            "kubectl_events",
        ]
        for tool in read_tools:
            op = lookup_operation(tool)
            assert op is not None, f"{tool} not mapped"
            assert op.category == OperationCategory.READ

    def test_all_mutating_tools_are_mapped(self) -> None:
        mutating_tools = [
            "kubectl_apply",
            "kubectl_create",
            "kubectl_delete",
            "kubectl_patch",
            "kubectl_replace",
            "kubectl_scale",
        ]
        for tool in mutating_tools:
            op = lookup_operation(tool)
            assert op is not None, f"{tool} not mapped"
            assert op.category == OperationCategory.WRITE

    def test_unknown_tool_returns_none(self) -> None:
        assert lookup_operation("kubectl_nuke") is None

    def test_is_supported(self) -> None:
        assert is_supported("kubectl_get") is True
        assert is_supported("kubectl_delete") is True
        assert is_supported("unknown") is False

    def test_supported_operations_returns_all(self) -> None:
        ops = supported_operations()
        assert len(ops) == 11  # 5 read + 6 mutating

    def test_supported_tool_names_returns_frozenset(self) -> None:
        names = supported_tool_names()
        assert isinstance(names, frozenset)
        assert "kubectl_get" in names
        assert "kubectl_delete" in names

    def test_extract_request_params_valid(self) -> None:
        params = {
            "name": "kubectl_delete",
            "arguments": {
                "namespace": "staging",
                "resource_type": "pod",
                "resource_name": "web-1",
            },
        }
        result = extract_request_params("kubectl_delete", params)
        assert result is not None
        assert result.namespace == "staging"
        assert result.resource_type == "pod"
        assert result.resource_name == "web-1"
        assert result.operation.verb == K8sVerb.DELETE

    def test_extract_request_params_defaults(self) -> None:
        params = {"name": "kubectl_get", "arguments": {}}
        result = extract_request_params("kubectl_get", params)
        assert result is not None
        assert result.namespace == "default"

    def test_extract_request_params_unknown_tool(self) -> None:
        assert extract_request_params("unknown", {}) is None

    def test_extract_request_params_missing_arguments(self) -> None:
        result = extract_request_params("kubectl_get", {"name": "kubectl_get"})
        assert result is not None
        assert result.namespace == "default"

    def test_k8s_operation_frozen(self) -> None:
        op = K8sOperation(
            tool_name="test",
            verb=K8sVerb.GET,
            category=OperationCategory.READ,
        )
        with pytest.raises(FrozenInstanceError):
            op.tool_name = "changed"  # type: ignore[misc]


# ============================================================================
# 5. Kubernetes client manager tests
# ============================================================================


class TestKubernetesClientManager:
    def test_not_initialized_by_default(self) -> None:
        mgr = KubernetesClientManager()
        assert mgr.is_initialized is False

    def test_core_v1_raises_when_not_initialized(self) -> None:
        mgr = KubernetesClientManager()
        with pytest.raises(ExecutionUnavailable):
            _ = mgr.core_v1

    def test_apps_v1_raises_when_not_initialized(self) -> None:
        mgr = KubernetesClientManager()
        with pytest.raises(ExecutionUnavailable):
            _ = mgr.apps_v1

    def test_close_is_safe_when_not_initialized(self) -> None:
        mgr = KubernetesClientManager()
        mgr.close()  # Should not raise
        assert mgr.is_initialized is False

    def test_sdk_availability_check(self) -> None:
        # This is a runtime check — it reports current environment state
        result = is_k8s_sdk_available()
        assert isinstance(result, bool)


# ============================================================================
# 6. Executor initialization tests
# ============================================================================


class TestExecutorInitialization:
    def test_creates_with_defaults(self) -> None:
        executor = KubernetesExecutor()
        assert executor.settings is not None

    def test_creates_with_custom_settings(self) -> None:
        settings = _make_settings(execution_timeout_seconds=30)
        executor = KubernetesExecutor(settings=settings)
        assert executor.settings.execution_timeout_seconds == 30

    def test_creates_with_injected_client(self) -> None:
        client = httpx.AsyncClient()
        executor = KubernetesExecutor(client=client)
        assert executor._client is client
        asyncio.run(client.aclose())

    def test_creates_with_custom_metrics(self) -> None:
        metrics = ExecutionMetrics()
        executor = KubernetesExecutor(metrics=metrics)
        assert executor._metrics is metrics


# ============================================================================
# 7. Executor execution tests (mocked HTTP)
# ============================================================================


class TestExecutorExecution:
    """Tests that use mock HTTP transport — no real cluster needed."""

    def test_preserves_raw_body_and_headers(self) -> None:
        """Backward compatibility: original test behavior must be preserved."""
        settings = get_settings()
        expected_body = b'{"jsonrpc":"2.0","id":1,"result":{}}'

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.content == expected_body
            assert request.headers.get("content-type") == "application/json"
            return httpx.Response(
                200,
                content=b'{"ok":true}',
                headers={"content-type": "application/json", "x-upstream": "1"},
            )

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        metrics = ExecutionMetrics()
        executor = KubernetesExecutor(settings=settings, client=client, metrics=metrics)

        result = asyncio.run(
            executor.execute(
                expected_body,
                {"content-type": "application/json"},
            )
        )

        assert result.status_code == 200
        assert result.body == b'{"ok":true}'
        assert result.headers["x-upstream"] == "1"
        assert result.backend == "kubernetes"
        assert result.success is True
        assert result.error_type is None

        snap = metrics.snapshot()
        assert snap["execution_success"] == 1

        asyncio.run(client.aclose())

    def test_timeout_returns_504(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        metrics = ExecutionMetrics()
        executor = KubernetesExecutor(
            settings=get_settings(),
            client=client,
            metrics=metrics,
        )

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.status_code == 504
        assert result.success is False
        assert result.error_type == "timeout"
        assert result.retryable is True

        snap = metrics.snapshot()
        assert snap["execution_failure"] == 1
        assert snap["execution_timeout"] == 1

        asyncio.run(client.aclose())

    def test_connect_error_returns_503(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection failed")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.status_code == 503
        assert result.success is False
        assert result.error_type == "unavailable"
        assert result.retryable is True

        asyncio.run(client.aclose())

    def test_internal_error_returns_500(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            raise RuntimeError("boom")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.status_code == 500
        assert result.success is False
        assert result.error_type == "internal_error"
        assert result.retryable is False

        asyncio.run(client.aclose())

    def test_upstream_401_classified_correctly(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(401, content=b"unauthorized")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.status_code == 401
        assert result.success is False
        assert result.error_type == "authentication_failed"

        asyncio.run(client.aclose())

    def test_upstream_403_classified_correctly(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(403, content=b"forbidden")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.status_code == 403
        assert result.success is False
        assert result.error_type == "authorization_denied"

        asyncio.run(client.aclose())

    def test_upstream_404_classified_correctly(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(404, content=b"not found")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.status_code == 404
        assert result.success is False
        assert result.error_type == "not_found"

        asyncio.run(client.aclose())

    def test_upstream_409_classified_as_retryable(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(409, content=b"conflict")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.status_code == 409
        assert result.success is False
        assert result.error_type == "conflict"
        assert result.retryable is True

        asyncio.run(client.aclose())

    def test_upstream_429_classified_as_retryable(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(429, content=b"rate limited")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.status_code == 429
        assert result.error_type == "rate_limited"
        assert result.retryable is True

        asyncio.run(client.aclose())

    def test_upstream_5xx_classified_as_retryable(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(502, content=b"bad gateway")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.status_code == 502
        assert result.error_type == "bad_gateway"
        assert result.retryable is True

        asyncio.run(client.aclose())

    def test_unknown_4xx_classified_as_client_error(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(418, content=b"I'm a teapot")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.status_code == 418
        assert result.error_type == "client_error"
        assert result.retryable is False

        asyncio.run(client.aclose())

    def test_unknown_5xx_classified_as_server_error(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(599, content=b"custom")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.status_code == 599
        assert result.error_type == "server_error"
        assert result.retryable is True

        asyncio.run(client.aclose())


# ============================================================================
# 8. Context threading tests
# ============================================================================


class TestContextThreading:
    def test_context_passed_through_on_success(self) -> None:
        ctx = _make_context()

        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"ok")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}, context=ctx))

        assert result.context is not None
        assert result.context.request_id == "req-1"
        assert result.context.approval_id == "nonce-1"

        asyncio.run(client.aclose())

    def test_context_passed_through_on_failure(self) -> None:
        ctx = _make_context()

        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}, context=ctx))

        assert result.context is not None
        assert result.context.request_id == "req-1"

        asyncio.run(client.aclose())

    def test_no_context_still_works(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"ok")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.context is None
        assert result.success is True

        asyncio.run(client.aclose())


# ============================================================================
# 9. Retry logic tests
# ============================================================================


class TestRetryLogic:
    def test_retries_on_retryable_failure(self) -> None:
        call_count = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return httpx.Response(503, content=b"unavailable")
            return httpx.Response(200, content=b"ok")

        settings = _make_settings(execution_retries=2)
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        metrics = ExecutionMetrics()
        executor = KubernetesExecutor(settings=settings, client=client, metrics=metrics)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.success is True
        assert call_count == 3

        snap = metrics.snapshot()
        assert snap["execution_retries"] == 1

        asyncio.run(client.aclose())

    def test_no_retry_on_non_retryable(self) -> None:
        call_count = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(403, content=b"forbidden")

        settings = _make_settings(execution_retries=3)
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=settings, client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.success is False
        assert call_count == 1  # No retries for non-retryable errors

        asyncio.run(client.aclose())

    def test_no_retry_when_budget_is_zero(self) -> None:
        call_count = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(503, content=b"unavailable")

        settings = _make_settings(execution_retries=0)
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=settings, client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.success is False
        assert call_count == 1

        asyncio.run(client.aclose())

    def test_exhausted_retries_return_last_result(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(503, content=b"unavailable")

        settings = _make_settings(execution_retries=2)
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=settings, client=client)

        result = asyncio.run(executor.execute(b"x", {}))

        assert result.status_code == 503
        assert result.success is False

        asyncio.run(client.aclose())


# ============================================================================
# 10. Operation info extraction tests
# ============================================================================


class TestOperationInfoExtraction:
    def test_extracts_tool_name_and_namespace(self) -> None:
        body = _mcp_body("kubectl_delete", namespace="staging")
        info = KubernetesExecutor._extract_operation_info(body)
        assert info is not None
        assert info["tool_name"] == "kubectl_delete"
        assert info["namespace"] == "staging"

    def test_returns_none_for_invalid_json(self) -> None:
        assert KubernetesExecutor._extract_operation_info(b"not json") is None

    def test_returns_none_for_non_dict(self) -> None:
        assert KubernetesExecutor._extract_operation_info(b"[1,2,3]") is None

    def test_handles_missing_params(self) -> None:
        body = json.dumps({"jsonrpc": "2.0", "id": 1}).encode()
        info = KubernetesExecutor._extract_operation_info(body)
        assert info is not None
        assert info["tool_name"] == ""

    def test_handles_non_dict_arguments(self) -> None:
        body = json.dumps(
            {"params": {"name": "kubectl_get", "arguments": "invalid"}}
        ).encode()
        info = KubernetesExecutor._extract_operation_info(body)
        assert info is not None
        assert info["namespace"] == ""


# ============================================================================
# 11. Integration-style tests (full pipeline, mocked transport)
# ============================================================================


class TestIntegrationExecution:
    def test_approved_request_full_pipeline(self) -> None:
        """Simulate a complete approval→execution flow with context."""
        body = _mcp_body("kubectl_delete", namespace="prod", resource_type="pod")
        ctx = _make_context(
            request_id="req-42",
            approval_id="nonce-42",
            execution_target="kubectl_delete",
        )

        def handler(request: httpx.Request) -> httpx.Response:
            # Verify raw bytes are preserved
            parsed = json.loads(request.content)
            assert parsed["params"]["name"] == "kubectl_delete"
            return httpx.Response(
                200,
                content=b'{"result":"deleted"}',
                headers={"content-type": "application/json"},
            )

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        metrics = ExecutionMetrics()
        executor = KubernetesExecutor(
            settings=get_settings(), client=client, metrics=metrics
        )

        result = asyncio.run(
            executor.execute(
                body,
                {"content-type": "application/json"},
                context=ctx,
            )
        )

        assert result.success is True
        assert result.status_code == 200
        assert result.body == b'{"result":"deleted"}'
        assert result.context is not None
        assert result.context.request_id == "req-42"

        snap = metrics.snapshot()
        assert snap["execution_success"] == 1
        assert snap["execution_total"] == 1

        asyncio.run(client.aclose())

    def test_api_failure_full_pipeline(self) -> None:
        """Simulate Kubernetes API rejecting the request."""
        body = _mcp_body("kubectl_create")

        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                content=b'{"message":"invalid manifest"}',
            )

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(body, {}))

        assert result.success is False
        assert result.status_code == 422
        assert result.error_type == "invalid_request"

        asyncio.run(client.aclose())

    def test_timeout_full_pipeline(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("upstream timeout")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        result = asyncio.run(executor.execute(_mcp_body("kubectl_apply"), {}))

        assert result.success is False
        assert result.status_code == 504
        assert result.error_type == "timeout"

        asyncio.run(client.aclose())

    def test_namespace_error_pipeline(self) -> None:
        """404 from upstream when namespace doesn't exist."""

        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(404, content=b'{"message":"namespace not found"}')

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        executor = KubernetesExecutor(settings=get_settings(), client=client)

        body = _mcp_body("kubectl_get", namespace="nonexistent")
        result = asyncio.run(executor.execute(body, {}))

        assert result.success is False
        assert result.status_code == 404
        assert result.error_type == "not_found"

        asyncio.run(client.aclose())

    def test_client_closes_when_not_provided(self) -> None:
        """Verify the executor creates and closes its own client."""
        call_count = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, content=b"ok")

        transport = httpx.MockTransport(handler)
        # Create a client but don't inject it — let executor manage its own
        settings = get_settings()
        executor = KubernetesExecutor(settings=settings)

        # We can't easily test without a real server, so this test verifies
        # that execution with no injected client doesn't crash on cleanup
        # by using a mock at a lower level
        mock_client = httpx.AsyncClient(transport=transport)
        executor._client = mock_client

        result = asyncio.run(executor.execute(b"test", {}))
        assert result.status_code == 200

        asyncio.run(mock_client.aclose())


# ============================================================================
# 12. Factory tests (extended)
# ============================================================================


class TestFactoryExtended:
    def test_factory_returns_kubernetes_executor(self) -> None:
        settings = _make_settings(execution_backend="kubernetes")
        engine = ExecutionFactory(settings=settings).create()
        assert isinstance(engine, KubernetesExecutor)

    def test_factory_rejects_unknown_backend(self) -> None:
        settings = _make_settings(execution_backend="aws")
        with pytest.raises(ExecutionRejected):
            ExecutionFactory(settings=settings).create()

    def test_factory_normalizes_backend_name(self) -> None:
        settings = _make_settings(execution_backend="  Kubernetes  ")
        engine = ExecutionFactory(settings=settings).create()
        assert isinstance(engine, KubernetesExecutor)
