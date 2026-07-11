from __future__ import annotations

import asyncio

import httpx

from app.config import get_settings
from app.execution.kubernetes_executor import KubernetesExecutor


def test_executor_preserves_raw_body_and_headers() -> None:
    settings = get_settings()
    expected_body = b'{"jsonrpc":"2.0","id":1,"result":{}}'

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.content == expected_body
        assert request.headers.get("content-type") == "application/json"
        assert request.headers.get("x-test") == "1"
        return httpx.Response(
            200,
            content=b'{"ok":true}',
            headers={"content-type": "application/json", "x-upstream": "1"},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    executor = KubernetesExecutor(settings=settings, client=client)

    result = asyncio.run(
        executor.execute(
            expected_body,
            {"content-type": "application/json", "x-test": "1"},
        )
    )

    assert result.status_code == 200
    assert result.body == b'{"ok":true}'
    assert result.headers["x-upstream"] == "1"
    assert result.backend == "kubernetes"
    assert result.success is True

    asyncio.run(client.aclose())


def test_executor_maps_timeout_to_504() -> None:
    settings = get_settings()

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    executor = KubernetesExecutor(settings=settings, client=client)

    result = asyncio.run(executor.execute(b"x", {}))

    assert result.status_code == 504
    assert result.success is False

    asyncio.run(client.aclose())


def test_executor_maps_unavailable_to_503() -> None:
    settings = get_settings()

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    executor = KubernetesExecutor(settings=settings, client=client)

    result = asyncio.run(executor.execute(b"x", {}))

    assert result.status_code == 503
    assert result.success is False

    asyncio.run(client.aclose())


def test_executor_maps_internal_error_to_500() -> None:
    settings = get_settings()

    def handler(_: httpx.Request) -> httpx.Response:
        raise RuntimeError("boom")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    executor = KubernetesExecutor(settings=settings, client=client)

    result = asyncio.run(executor.execute(b"x", {}))

    assert result.status_code == 500
    assert result.success is False

    asyncio.run(client.aclose())