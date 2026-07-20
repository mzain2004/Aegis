"""Function-tool schemas mirroring Kubernetes MCP tools for local bridge mode."""

from __future__ import annotations

from typing import Any

from app.tool_policy import MUTATING_TOOLS, READ_ONLY_TOOLS

_TOOL_DESCRIPTIONS: dict[str, str] = {
    "kubectl_get": "Read Kubernetes resources (pods, deployments, services, etc.).",
    "kubectl_describe": "Describe a Kubernetes resource in detail.",
    "kubectl_logs": "Fetch container logs for a pod.",
    "kubectl_top": "Show resource usage (CPU/memory) for nodes or pods.",
    "kubectl_events": "List Kubernetes events for diagnosis.",
    "kubectl_apply": (
        "Apply a Kubernetes manifest. Requires human approval via Veto Ops."
    ),
    "kubectl_create": (
        "Create a Kubernetes resource. Requires human approval via Veto Ops."
    ),
    "kubectl_delete": (
        "Delete a Kubernetes resource. Requires human approval via Veto Ops."
    ),
    "kubectl_patch": (
        "Patch a Kubernetes resource. Requires human approval via Veto Ops."
    ),
    "kubectl_replace": (
        "Replace a Kubernetes resource. Requires human approval via Veto Ops."
    ),
    "kubectl_scale": "Scale a workload. Requires human approval via Veto Ops.",
}


def _parameters_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "Full kubectl-style argument string after the tool verb, "
                    "for example: 'pods -n payments' or "
                    "'-f -' with manifest YAML supplied in 'manifest'."
                ),
            },
            "namespace": {
                "type": "string",
                "description": "Optional Kubernetes namespace.",
            },
            "manifest": {
                "type": "string",
                "description": "Optional YAML/JSON manifest for apply/create/replace.",
            },
            "args": {
                "type": "object",
                "description": (
                    "Optional structured arguments forwarded to the MCP tool."
                ),
                "additionalProperties": True,
            },
        },
        "additionalProperties": True,
    }


def build_function_tools() -> list[dict[str, Any]]:
    """Build Responses API function tools for all known Kubernetes MCP tools."""

    tools: list[dict[str, Any]] = []
    for name in sorted(READ_ONLY_TOOLS | MUTATING_TOOLS):
        description = _TOOL_DESCRIPTIONS.get(
            name,
            f"Kubernetes MCP tool '{name}'. Mutating tools are approval-gated.",
        )
        if name in MUTATING_TOOLS:
            description += (
                " This mutation is intercepted by Veto Ops and may return "
                "pending_approval until a human signs the HMAC challenge."
            )
        tools.append(
            {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": _parameters_schema(),
            }
        )
    return tools
