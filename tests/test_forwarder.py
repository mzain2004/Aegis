"""Tests for MCPForwarder behavior."""

from __future__ import annotations

import asyncio

import httpx

from app.config import get_settings
from app.forwarder import MCPForwarder


def test_forwarder_preserves_body_and_headers() -> None:
    settings = get_settings()

    expected_body = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

    def handler(request: httpx.Request) -> httpx.Response:
        # Ensure body preserved
        assert request.content == expected_body
        # Ensure headers preserved (content-type)
        assert request.headers.get("content-type") == "application/json"
        return httpx.Response(
            200, content=b'{"result":{}}', headers={"content-type": "application/json"}
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    forwarder = MCPForwarder(settings=settings, client=client)

    status, body, headers = asyncio.run(
        forwarder.forward(expected_body, {"content-type": "application/json"})
    )

    assert status == 200
    assert body == b'{"result":{}}'
    assert headers.get("content-type") == "application/json"


def test_forwarder_handles_connect_error() -> None:
    settings = get_settings()

    def handler(_: httpx.Request) -> httpx.Response:  # simulate connection error
        raise httpx.ConnectError("connection failed")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    forwarder = MCPForwarder(settings=settings, client=client)

    status, body, headers = asyncio.run(forwarder.forward(b"x", {}))

    assert status == 503


def test_forwarder_handles_timeout() -> None:
    settings = get_settings()

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timeout")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    forwarder = MCPForwarder(settings=settings, client=client)

    status, body, headers = asyncio.run(forwarder.forward(b"x", {}))

    assert status == 504
