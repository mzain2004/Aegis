"""Integration-style tests for the proxy endpoint using dependency overrides."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app import dependencies
from app.config import get_settings
from app.forwarder import MCPForwarder
from app.main import app


def test_proxy_forwards_response_and_headers() -> None:
    settings = get_settings()

    expected_body = b'{"jsonrpc":"2.0","id":1,"result":{}}'

    def handler(request: httpx.Request) -> httpx.Response:
        # Return the same bytes and a custom header
        return httpx.Response(
            200,
            content=expected_body,
            headers={"content-type": "application/json", "x-custom": "1"},
        )

    transport = httpx.MockTransport(handler)
    client_async = httpx.AsyncClient(transport=transport)
    forwarder = MCPForwarder(settings=settings, client=client_async)

    # Override dependency to use our forwarder
    app.dependency_overrides[dependencies.get_forwarder] = lambda: forwarder

    with TestClient(app) as client:
        resp = client.post(
            "/",
            content=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.content == expected_body
        assert resp.headers.get("x-custom") == "1"

    app.dependency_overrides.clear()


def test_proxy_returns_503_when_downstream_unavailable() -> None:
    settings = get_settings()

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed")

    transport = httpx.MockTransport(handler)
    client_async = httpx.AsyncClient(transport=transport)
    forwarder = MCPForwarder(settings=settings, client=client_async)

    app.dependency_overrides[dependencies.get_forwarder] = lambda: forwarder

    with TestClient(app) as client:
        resp = client.post("/", content=b"x")
        assert resp.status_code == 503

    app.dependency_overrides.clear()


def test_proxy_returns_504_on_timeout() -> None:
    settings = get_settings()

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    transport = httpx.MockTransport(handler)
    client_async = httpx.AsyncClient(transport=transport)
    forwarder = MCPForwarder(settings=settings, client=client_async)

    app.dependency_overrides[dependencies.get_forwarder] = lambda: forwarder

    with TestClient(app) as client:
        resp = client.post("/", content=b"x")
        assert resp.status_code == 504

    app.dependency_overrides.clear()
