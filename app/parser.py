"""Placeholder RPC parser for future MCP JSON-RPC inspection.

This module intentionally does not parse or classify payloads yet.

TODO: add JSON-RPC parsing, tool extraction, and request classification once
the proxy inspection phase begins.
"""

from __future__ import annotations

from typing import Any

from app.logger import get_logger

LOGGER = get_logger(__name__)


class RPCParser:
    """Skeleton parser for future MCP and JSON-RPC handling."""

    def parse(self, payload: str | bytes | dict[str, Any]) -> Any:
        """Parse an RPC payload.

        TODO: decode transport-specific payloads and normalize them into a
        structured request representation.
        """

        LOGGER.debug("rpc_parse_not_implemented")
        raise NotImplementedError("RPC parsing is reserved for a later phase.")

    def classify(self, payload: Any) -> str:
        """Classify a parsed request.

        TODO: distinguish read-only, mutating, and approval-gated requests.
        """

        LOGGER.debug("rpc_classify_not_implemented")
        raise NotImplementedError("RPC classification is reserved for a later phase.")

    def extract_tool(self, payload: Any) -> str:
        """Extract the MCP tool name from a parsed request.

        TODO: map the future JSON-RPC envelope to a canonical tool identifier.
        """

        LOGGER.debug("rpc_extract_tool_not_implemented")
        raise NotImplementedError("Tool extraction is reserved for a later phase.")
