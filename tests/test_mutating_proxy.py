from __future__ import annotations

import httpx

from fastapi.testclient import TestClient

from app import dependencies
from app.config import get_settings
from app.forwarder import MCPForwarder
from app.main import app
from app.pending_store import PendingRequestStore


def test_read_only_request_is_forwarded() -> None:
    settings = get_settings()

    expected_body = b'{"jsonrpc":"2.0","id":1,"result":{}}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=expected_body,
            headers={"content-type": "application/json", "x-custom": "1"},
        )

    transport = httpx.MockTransport(handler)
    client_async = httpx.AsyncClient(transport=transport)
    forwarder = MCPForwarder(settings=settings, client=client_async)
    store = PendingRequestStore(ttl_seconds=300)

    app.dependency_overrides[dependencies.get_forwarder] = lambda: forwarder
    app.dependency_overrides[dependencies.get_pending_store] = lambda: store

    with TestClient(app) as client:
        resp = client.post(
            "/",
            content=b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"kubectl_get"}}',
            headers={"content-type": "application/json"},
        )

        assert resp.status_code == 200
        assert resp.content == expected_body
        assert resp.headers.get("x-custom") == "1"
        assert store.count() == 0

    app.dependency_overrides.clear()


def test_mutating_request_is_suspended() -> None:
    settings = get_settings()

    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("mutating request must not be forwarded")

    transport = httpx.MockTransport(handler)
    client_async = httpx.AsyncClient(transport=transport)
    forwarder = MCPForwarder(settings=settings, client=client_async)
    store = PendingRequestStore(ttl_seconds=300)

    app.dependency_overrides[dependencies.get_forwarder] = lambda: forwarder
    app.dependency_overrides[dependencies.get_pending_store] = lambda: store

    with TestClient(app) as client:
        resp = client.post(
            "/",
            content=b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"kubectl_delete"}}',
            headers={"content-type": "application/json"},
        )

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "pending_approval"
        assert body["expires_in"] == 300
        assert store.count() == 1
        assert store.exists(body["nonce"])

    app.dependency_overrides.clear()