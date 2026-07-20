"""Tests for the Veto Ops HTTP JSON-RPC bridge."""

from __future__ import annotations

import json

import httpx
import pytest

from agent.bridge import VetoProxyBridge
from agent.config import AgentSettings


@pytest.mark.asyncio
async def test_bridge_posts_tools_call_to_veto_proxy() -> None:
    settings = AgentSettings(
        DASHSCOPE_API_KEY="sk-test-key-123456",
        VETO_PROXY_URL="http://127.0.0.1:9000",
    )
    recorded: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded["url"] = str(request.url)
        recorded["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": "1", "result": {"content": "ok"}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        bridge = VetoProxyBridge(settings=settings, client=client)
        result = await bridge.call_tool(
            "kubectl_get",
            {"command": "pods -n payments"},
        )

    assert recorded["url"] == "http://127.0.0.1:9000/"
    body = recorded["body"]
    assert isinstance(body, dict)
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "kubectl_get"
    assert result.status_code == 200
    assert result.pending_approval is False


@pytest.mark.asyncio
async def test_bridge_detects_pending_approval() -> None:
    settings = AgentSettings(
        DASHSCOPE_API_KEY="sk-test-key-123456",
        VETO_PROXY_URL="http://127.0.0.1:9000",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            json={
                "status": "pending_approval",
                "nonce": "nonce-1",
                "expires_in": 300,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        bridge = VetoProxyBridge(settings=settings, client=client)
        result = await bridge.call_tool("kubectl_delete", {"command": "ns/evil"})

    assert result.pending_approval is True
    assert result.nonce == "nonce-1"
    assert result.expires_in == 300
    assert "pending_approval" in result.as_tool_output()
    assert "do not immediately retry" in result.as_tool_output().lower()


@pytest.mark.asyncio
async def test_bridge_timeout_is_normalized() -> None:
    settings = AgentSettings(
        DASHSCOPE_API_KEY="sk-test-key-123456",
        VETO_PROXY_URL="http://127.0.0.1:9000",
        AGENT_MCP_BRIDGE_TIMEOUT_SECONDS=0.01,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        bridge = VetoProxyBridge(settings=settings, client=client)
        result = await bridge.call_tool("kubectl_get", {})

    assert result.timed_out is True
    assert result.error is not None
