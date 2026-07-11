"""Tool classification policy for MCP request inspection."""

from __future__ import annotations

READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "kubectl_get",
        "kubectl_describe",
        "kubectl_logs",
        "kubectl_top",
        "kubectl_events",
    }
)

MUTATING_TOOLS: frozenset[str] = frozenset(
    {
        "kubectl_apply",
        "kubectl_create",
        "kubectl_delete",
        "kubectl_patch",
        "kubectl_replace",
        "kubectl_scale",
    }
)