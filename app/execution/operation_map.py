"""Operation mapping for MCP tool calls to Kubernetes API actions.

This module translates approved MCP tool names into structured Kubernetes
operation descriptors. It is a pure-data translation layer — no Kubernetes
API calls happen here.

Security: the mapper only translates operations already approved through
the approval pipeline. It does not make authorization decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class K8sVerb(StrEnum):
    """Kubernetes API verb corresponding to an MCP tool."""

    GET = "get"
    LIST = "list"
    CREATE = "create"
    UPDATE = "update"
    PATCH = "patch"
    DELETE = "delete"
    DESCRIBE = "describe"
    LOGS = "logs"
    TOP = "top"
    EVENTS = "events"
    APPLY = "apply"
    REPLACE = "replace"
    SCALE = "scale"


class OperationCategory(StrEnum):
    """Whether the operation mutates cluster state."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class K8sOperation:
    """Describes a single Kubernetes operation derived from an MCP tool call."""

    tool_name: str
    verb: K8sVerb
    category: OperationCategory
    description: str = ""
    supports_namespace: bool = True
    supports_resource_type: bool = True


# ---------------------------------------------------------------------------
# Canonical operation registry
# ---------------------------------------------------------------------------

_OPERATION_MAP: dict[str, K8sOperation] = {
    # Read-only operations
    "kubectl_get": K8sOperation(
        tool_name="kubectl_get",
        verb=K8sVerb.GET,
        category=OperationCategory.READ,
        description="Retrieve one or more resources.",
    ),
    "kubectl_describe": K8sOperation(
        tool_name="kubectl_describe",
        verb=K8sVerb.DESCRIBE,
        category=OperationCategory.READ,
        description="Show detailed information about a resource.",
    ),
    "kubectl_logs": K8sOperation(
        tool_name="kubectl_logs",
        verb=K8sVerb.LOGS,
        category=OperationCategory.READ,
        description="Fetch container logs.",
        supports_resource_type=False,
    ),
    "kubectl_top": K8sOperation(
        tool_name="kubectl_top",
        verb=K8sVerb.TOP,
        category=OperationCategory.READ,
        description="Display resource usage metrics.",
    ),
    "kubectl_events": K8sOperation(
        tool_name="kubectl_events",
        verb=K8sVerb.EVENTS,
        category=OperationCategory.READ,
        description="List cluster events.",
        supports_resource_type=False,
    ),
    # Mutating operations
    "kubectl_apply": K8sOperation(
        tool_name="kubectl_apply",
        verb=K8sVerb.APPLY,
        category=OperationCategory.WRITE,
        description="Apply a configuration to a resource.",
    ),
    "kubectl_create": K8sOperation(
        tool_name="kubectl_create",
        verb=K8sVerb.CREATE,
        category=OperationCategory.WRITE,
        description="Create a new resource.",
    ),
    "kubectl_delete": K8sOperation(
        tool_name="kubectl_delete",
        verb=K8sVerb.DELETE,
        category=OperationCategory.WRITE,
        description="Delete a resource.",
    ),
    "kubectl_patch": K8sOperation(
        tool_name="kubectl_patch",
        verb=K8sVerb.PATCH,
        category=OperationCategory.WRITE,
        description="Partially update a resource.",
    ),
    "kubectl_replace": K8sOperation(
        tool_name="kubectl_replace",
        verb=K8sVerb.REPLACE,
        category=OperationCategory.WRITE,
        description="Replace a resource definition entirely.",
    ),
    "kubectl_scale": K8sOperation(
        tool_name="kubectl_scale",
        verb=K8sVerb.SCALE,
        category=OperationCategory.WRITE,
        description="Set a new replica count for a workload.",
    ),
}


def lookup_operation(tool_name: str) -> K8sOperation | None:
    """Return the operation descriptor for a supported tool, or ``None``."""
    return _OPERATION_MAP.get(tool_name)


def is_supported(tool_name: str) -> bool:
    """Return ``True`` if the tool is in the supported operation set."""
    return tool_name in _OPERATION_MAP


def supported_operations() -> list[K8sOperation]:
    """Return a snapshot of all registered operations."""
    return list(_OPERATION_MAP.values())


def supported_tool_names() -> frozenset[str]:
    """Return the set of supported tool names."""
    return frozenset(_OPERATION_MAP.keys())


# ---------------------------------------------------------------------------
# Request parameter extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class K8sRequestParams:
    """Structured parameters extracted from an MCP tool call payload."""

    tool_name: str
    operation: K8sOperation
    namespace: str = "default"
    resource_type: str = ""
    resource_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


def extract_request_params(
    tool_name: str,
    params: dict[str, Any],
) -> K8sRequestParams | None:
    """Extract structured parameters from the MCP ``params`` dict.

    Returns ``None`` if the tool is not recognized.
    """
    operation = lookup_operation(tool_name)
    if operation is None:
        return None

    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}

    return K8sRequestParams(
        tool_name=tool_name,
        operation=operation,
        namespace=arguments.get("namespace", "default"),
        resource_type=arguments.get("resource_type", ""),
        resource_name=arguments.get("resource_name", ""),
        arguments=arguments,
    )
