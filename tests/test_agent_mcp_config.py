"""Tests for MCP tool configuration aimed at the Veto Ops proxy."""

from __future__ import annotations

import pytest

from agent.config import AgentSettings
from agent.mcp_config import (
    VETO_MCP_SERVER_LABEL,
    build_remote_mcp_tool,
    resolve_tools_for_mode,
)


def test_build_remote_mcp_tool_points_at_veto_sse() -> None:
    settings = AgentSettings(
        DASHSCOPE_API_KEY="sk-test-key-123456",
        VETO_MCP_SSE_URL="https://tunnel.example/sse",
        AGENT_TOOL_MODE="remote_mcp",
    )

    tool = build_remote_mcp_tool(settings)

    assert tool["type"] == "mcp"
    assert tool["server_protocol"] == "sse"
    assert tool["server_label"] == VETO_MCP_SERVER_LABEL
    assert tool["server_url"] == "https://tunnel.example/sse"
    assert (
        "guard" in tool["server_description"].lower()
        or "veto" in tool["server_description"].lower()
    )


def test_remote_mcp_requires_sse_url() -> None:
    settings = AgentSettings(
        DASHSCOPE_API_KEY="sk-test-key-123456",
        VETO_MCP_SSE_URL="",
        AGENT_TOOL_MODE="remote_mcp",
    )

    with pytest.raises(ValueError, match="VETO_MCP_SSE_URL"):
        build_remote_mcp_tool(settings)


def test_bridge_mode_uses_function_tools() -> None:
    settings = AgentSettings(
        DASHSCOPE_API_KEY="sk-test-key-123456",
        AGENT_TOOL_MODE="bridge",
    )

    tools = resolve_tools_for_mode(settings)

    assert tools
    assert all(tool["type"] == "function" for tool in tools)
    names = {tool["name"] for tool in tools}
    assert "kubectl_get" in names
    assert "kubectl_delete" in names
