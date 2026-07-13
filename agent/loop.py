"""Primary Qwen Responses API agent loop with context chaining."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from agent.bridge import AegisMCPBridge
from agent.client import build_extra_body, create_async_openai_client
from agent.config import AgentSettings, get_agent_settings
from agent.mcp_config import resolve_tools_for_mode
from agent.prompts import SYSTEM_INSTRUCTIONS, build_incident_prompt


@dataclass(slots=True)
class FunctionCallRequest:
    """One function_call item extracted from a Responses API output."""

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class AgentRunResult:
    """Final outcome of an incident investigation loop."""

    final_text: str
    response_ids: list[str] = field(default_factory=list)
    turn_count: int = 0
    pending_approvals: list[str] = field(default_factory=list)
    stopped_reason: str = "completed"


def parse_function_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    """Parse function-call arguments from SDK objects or JSON strings."""

    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    text = raw.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"command": text}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


def extract_function_calls(response: Any) -> list[FunctionCallRequest]:
    """Extract function_call output items from a Responses API response."""

    calls: list[FunctionCallRequest] = []
    output = getattr(response, "output", None) or []
    for item in output:
        item_type = getattr(item, "type", None)
        if item_type is None and isinstance(item, dict):
            item_type = item.get("type")
        if item_type != "function_call":
            continue

        if isinstance(item, dict):
            call_id = str(item.get("call_id") or item.get("id") or "")
            name = str(item.get("name") or "")
            arguments = parse_function_arguments(item.get("arguments"))
        else:
            call_id = str(
                getattr(item, "call_id", None) or getattr(item, "id", "") or ""
            )
            name = str(getattr(item, "name", "") or "")
            arguments = parse_function_arguments(getattr(item, "arguments", None))

        if call_id and name:
            calls.append(
                FunctionCallRequest(call_id=call_id, name=name, arguments=arguments)
            )
    return calls


def response_output_text(response: Any) -> str:
    """Best-effort extraction of assistant text from a response object."""

    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    chunks: list[str] = []
    for item in getattr(response, "output", None) or []:
        item_type = getattr(item, "type", None)
        if item_type is None and isinstance(item, dict):
            item_type = item.get("type")
        if item_type != "message":
            continue
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content")
        for part in content or []:
            if isinstance(part, dict):
                if part.get("type") in {"output_text", "text"} and part.get("text"):
                    chunks.append(str(part["text"]))
            else:
                part_type = getattr(part, "type", None)
                part_text = getattr(part, "text", None)
                if part_type in {"output_text", "text"} and part_text:
                    chunks.append(str(part_text))
    return "\n".join(chunks).strip()


class QwenSafeOpsAgent:
    """Single-agent SRE loop over Qwen3.7-Max Responses API + Aegis tools."""

    def __init__(
        self,
        settings: AgentSettings | None = None,
        client: AsyncOpenAI | None = None,
        bridge: AegisMCPBridge | None = None,
    ) -> None:
        self.settings = settings or get_agent_settings()
        self._client = client
        self._bridge = bridge
        self._owns_client = client is None
        self._owns_bridge = bridge is None

    async def __aenter__(self) -> QwenSafeOpsAgent:
        if self._client is None:
            self._client = create_async_openai_client(self.settings)
        if self._bridge is None and self.settings.tool_mode == "bridge":
            self._bridge = AegisMCPBridge(self.settings)
            await self._bridge.__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._owns_bridge and self._bridge is not None:
            await self._bridge.__aexit__(*exc_info)
            self._bridge = None
        if self._owns_client and self._client is not None:
            await self._client.close()
            self._client = None

    async def _create_response(
        self,
        *,
        input_payload: Any,
        previous_response_id: str | None,
    ) -> Any:
        if self._client is None:
            raise RuntimeError(
                "QwenSafeOpsAgent must be used as an async context manager"
            )

        kwargs: dict[str, Any] = {
            "model": self.settings.qwen_model,
            "input": input_payload,
            "instructions": SYSTEM_INSTRUCTIONS,
            "tools": resolve_tools_for_mode(self.settings),
            "store": True,
        }
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id

        extra_body = build_extra_body(self.settings)
        if extra_body:
            kwargs["extra_body"] = extra_body

        return await self._client.responses.create(**kwargs)

    async def _execute_function_calls(
        self,
        calls: list[FunctionCallRequest],
        pending_approvals: list[str],
    ) -> list[dict[str, str]]:
        if self._bridge is None:
            raise RuntimeError("bridge tool mode requires an AegisMCPBridge")

        outputs: list[dict[str, str]] = []
        for call in calls:
            result = await self._bridge.call_tool(call.name, call.arguments)
            if result.pending_approval and result.nonce:
                pending_approvals.append(result.nonce)
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": result.as_tool_output(),
                }
            )
        return outputs

    async def run_incident(self, alert_context: str) -> AgentRunResult:
        """Run the diagnostic/remediation loop for one alert."""

        previous_response_id: str | None = None
        input_payload: Any = build_incident_prompt(alert_context)
        response_ids: list[str] = []
        pending_approvals: list[str] = []
        final_text = ""

        for turn in range(1, self.settings.max_turns + 1):
            response = await self._create_response(
                input_payload=input_payload,
                previous_response_id=previous_response_id,
            )
            response_id = str(getattr(response, "id", "") or "")
            if response_id:
                response_ids.append(response_id)
                previous_response_id = response_id

            final_text = response_output_text(response)
            function_calls = extract_function_calls(response)

            if self.settings.tool_mode == "remote_mcp":
                # DashScope executes remote MCP server-side within the response.
                return AgentRunResult(
                    final_text=final_text,
                    response_ids=response_ids,
                    turn_count=turn,
                    pending_approvals=pending_approvals,
                    stopped_reason="completed",
                )

            if not function_calls:
                return AgentRunResult(
                    final_text=final_text,
                    response_ids=response_ids,
                    turn_count=turn,
                    pending_approvals=pending_approvals,
                    stopped_reason="completed",
                )

            input_payload = await self._execute_function_calls(
                function_calls, pending_approvals
            )

        return AgentRunResult(
            final_text=final_text
            or (
                "Reached AGENT_MAX_TURNS before the model finished. "
                "Review pending approvals and continue with a follow-up turn."
            ),
            response_ids=response_ids,
            turn_count=self.settings.max_turns,
            pending_approvals=pending_approvals,
            stopped_reason="max_turns",
        )
