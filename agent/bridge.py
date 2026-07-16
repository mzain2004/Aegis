"""Local HTTP JSON-RPC bridge from the agent to the Aegis proxy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

from agent.config import AgentSettings, get_agent_settings


@dataclass(frozen=True, slots=True)
class BridgeResult:
    """Normalized result of one MCP tools/call through Aegis."""

    status_code: int
    body_text: str
    pending_approval: bool
    nonce: str | None
    expires_in: int | None
    timed_out: bool
    error: str | None = None

    def as_tool_output(self) -> str:
        """Serialize a model-facing tool result string."""

        payload: dict[str, Any] = {
            "http_status": self.status_code,
            "pending_approval": self.pending_approval,
            "timed_out": self.timed_out,
            "nonce": self.nonce,
            "expires_in": self.expires_in,
            "error": self.error,
            "body": self.body_text,
        }
        if self.pending_approval:
            payload["operator_hint"] = (
                "Mutation suspended by Aegis. Wait for out-of-band human approval; "
                "do not immediately retry the same mutating call."
            )
        if self.timed_out:
            payload["operator_hint"] = (
                "Tool call timed out while waiting on Aegis or upstream. Treat as "
                "approval ignore/timeout unless a later approval result arrives."
            )
        return json.dumps(payload, ensure_ascii=True)


class AegisMCPBridge:
    """POST MCP JSON-RPC ``tools/call`` requests to Engineer 1's Aegis proxy."""

    def __init__(
        self,
        settings: AgentSettings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_agent_settings()
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> AegisMCPBridge:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.settings.mcp_bridge_timeout_seconds
            )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _build_tools_call(self, tool_name: str, arguments: dict[str, Any]) -> bytes:
        request_id = str(uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> BridgeResult:
        """Invoke a tool through Aegis and normalize pending-approval responses."""

        if self._client is None:
            raise RuntimeError(
                "AegisMCPBridge must be used as an async context manager"
            )

        body = self._build_tools_call(tool_name, arguments or {})
        try:
            response = await self._client.post(
                f"{self.settings.aegis_proxy_url}/",
                content=body,
                headers={"content-type": "application/json"},
            )
        except httpx.TimeoutException as exc:
            return BridgeResult(
                status_code=0,
                body_text="",
                pending_approval=False,
                nonce=None,
                expires_in=None,
                timed_out=True,
                error=f"timeout contacting Aegis proxy: {exc}",
            )
        except httpx.HTTPError as exc:
            return BridgeResult(
                status_code=0,
                body_text="",
                pending_approval=False,
                nonce=None,
                expires_in=None,
                timed_out=False,
                error=f"transport error contacting Aegis proxy: {exc}",
            )

        text = response.text
        pending = False
        nonce: str | None = None
        expires_in: int | None = None

        try:
            parsed = response.json()
        except ValueError:
            parsed = None

        if isinstance(parsed, dict):
            if (
                parsed.get("status") == "pending_approval"
                or response.status_code == 202
            ):
                pending = True
                raw_nonce = parsed.get("nonce")
                nonce = raw_nonce if isinstance(raw_nonce, str) else None
                raw_expires = parsed.get("expires_in")
                expires_in = raw_expires if isinstance(raw_expires, int) else None
            text = json.dumps(parsed, ensure_ascii=True)

        return BridgeResult(
            status_code=response.status_code,
            body_text=text,
            pending_approval=pending,
            nonce=nonce,
            expires_in=expires_in,
            timed_out=False,
            error=None,
        )
