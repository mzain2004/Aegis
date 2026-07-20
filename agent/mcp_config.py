"""MCP tool configuration aimed at the Veto Ops execution-guard proxy."""

from __future__ import annotations

from typing import Any

from agent.config import AgentSettings, get_agent_settings

VETO_MCP_SERVER_LABEL = "veto-ops-k8s-guard"
VETO_MCP_SERVER_DESCRIPTION = (
    "Zero-trust Kubernetes MCP execution guard. Read-only tools pass through; "
    "mutating tools are suspended until out-of-band human HMAC approval."
)

# Backward-compatible aliases for older imports/tests.
AEGIS_MCP_SERVER_LABEL = VETO_MCP_SERVER_LABEL
AEGIS_MCP_SERVER_DESCRIPTION = VETO_MCP_SERVER_DESCRIPTION


def build_remote_mcp_tool(settings: AgentSettings | None = None) -> dict[str, Any]:
    """Build a Responses API ``mcp`` tool entry pointing at Veto Ops.

    DashScope currently requires SSE for remote MCP. Set ``VETO_MCP_SSE_URL`` to
    a publicly reachable SSE endpoint that fronts the Veto Ops proxy (or an SSE
    facade in front of it). Local ``http://127.0.0.1`` URLs are not reachable
    from Model Studio.
    """

    cfg = settings or get_agent_settings()
    server_url = cfg.veto_mcp_sse_url.strip()
    if not server_url:
        raise ValueError(
            "VETO_MCP_SSE_URL is required for remote_mcp tool mode. "
            "Use AGENT_TOOL_MODE=bridge for local HTTP JSON-RPC against "
            "VETO_PROXY_URL."
        )

    return {
        "type": "mcp",
        "server_protocol": "sse",
        "server_label": VETO_MCP_SERVER_LABEL,
        "server_description": VETO_MCP_SERVER_DESCRIPTION,
        "server_url": server_url,
    }


def resolve_tools_for_mode(
    settings: AgentSettings | None = None,
) -> list[dict[str, Any]]:
    """Return the tools array for the configured agent tool mode."""

    cfg = settings or get_agent_settings()
    if cfg.tool_mode == "remote_mcp":
        return [build_remote_mcp_tool(cfg)]

    from agent.tools import build_function_tools

    return build_function_tools()
