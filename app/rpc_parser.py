"""MCP JSON-RPC request parsing and classification."""

from __future__ import annotations

import json
from enum import Enum

from pydantic import BaseModel

from app.tool_policy import MUTATING_TOOLS, READ_ONLY_TOOLS


class OperationType(str, Enum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"
    UNKNOWN = "unknown"


class MCPRequestInfo(BaseModel):
    jsonrpc: str | None = None
    request_id: str | int | None = None
    method: str | None = None
    tool_name: str | None = None
    operation: OperationType = OperationType.UNKNOWN


def parse_mcp_request(body: bytes) -> MCPRequestInfo:
    """Parse raw MCP JSON-RPC bytes into a classification record.

    The parser never mutates the payload and always fails safely by returning
    an UNKNOWN operation when the body cannot be parsed.
    """

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return MCPRequestInfo(operation=OperationType.UNKNOWN)

    if not isinstance(payload, dict):
        return MCPRequestInfo(operation=OperationType.UNKNOWN)

    jsonrpc = payload.get("jsonrpc")
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params")

    tool_name: str | None = None
    if isinstance(params, dict):
        raw_tool_name = params.get("name")
        if isinstance(raw_tool_name, str):
            tool_name = raw_tool_name

    operation = OperationType.UNKNOWN
    if tool_name in READ_ONLY_TOOLS:
        operation = OperationType.READ_ONLY
    elif tool_name in MUTATING_TOOLS:
        operation = OperationType.MUTATING

    return MCPRequestInfo(
        jsonrpc=jsonrpc if isinstance(jsonrpc, str) else None,
        request_id=request_id if isinstance(request_id, (str, int)) else None,
        method=method if isinstance(method, str) else None,
        tool_name=tool_name,
        operation=operation,
    )