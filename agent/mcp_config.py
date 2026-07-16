"""MCP tool configuration aimed at the Aegis execution-guard proxy."""

from __future__ import annotations

from typing import Any

from agent.config import AgentSettings, get_agent_settings

AEGIS_MCP_SERVER_LABEL = "aegis-k8s-guard"
AEGIS_MCP_SERVER_DESCRIPTION = (
    "Zero-trust Kubernetes MCP execution guard. Read-only tools pass through; "
    "mutating tools are suspended until out-of-band human HMAC approval."
)


def build_remote_mcp_tool(settings: AgentSettings | None = None) -> dict[str, Any]:
    """Build a Responses API ``mcp`` tool entry pointing at Aegis.

    DashScope currently requires SSE for remote MCP. Set ``AEGIS_MCP_SSE_URL`` to
    a publicly reachable SSE endpoint that fronts the Aegis proxy (or an SSE
    facade in front of it). Local ``http://127.0.0.1`` URLs are not reachable
    from Model Studio.
    """

    cfg = settings or get_agent_settings()
    server_url = cfg.aegis_mcp_sse_url.strip()
    if not server_url:
        raise ValueError(
            "AEGIS_MCP_SSE_URL is required for remote_mcp tool mode. "
            "Use AGENT_TOOL_MODE=bridge for local HTTP JSON-RPC against "
            "AEGIS_PROXY_URL."
        )

    return {
        "type": "mcp",
        "server_protocol": "sse",
        "server_label": AEGIS_MCP_SERVER_LABEL,
        "server_description": AEGIS_MCP_SERVER_DESCRIPTION,
        "server_url": server_url,
    }


def resolve_tools_for_mode(
    settings: AgentSettings | None = None,
) -> list[dict[str, Any]]:
    """Return the tools array for the configured agent tool mode."""

    cfg = settings or get_agent_settings()
    if cfg.tool_mode == "remote_mcp":
        return [build_remote_mcp_tool(cfg)]

    # Imported lazily to keep mcp_config free of function-schema coupling for tests.
    from agent.tools import build_function_tools

    return build_function_tools()
