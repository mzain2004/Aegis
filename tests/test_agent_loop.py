"""Tests for the Qwen Responses API agent loop."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent.bridge import BridgeResult
from agent.config import AgentSettings
from agent.loop import (
    VetoOpsAgent,
    extract_function_calls,
    parse_function_arguments,
    response_output_text,
)


def test_parse_function_arguments() -> None:
    assert parse_function_arguments('{"command":"pods"}') == {"command": "pods"}
    assert parse_function_arguments("pods -n x") == {"command": "pods -n x"}
    assert parse_function_arguments({"namespace": "x"}) == {"namespace": "x"}


def test_extract_function_calls_from_sdk_like_objects() -> None:
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="call_1",
                name="kubectl_get",
                arguments='{"command":"pods"}',
            ),
            SimpleNamespace(type="message", content=[]),
        ]
    )

    calls = extract_function_calls(response)
    assert len(calls) == 1
    assert calls[0].name == "kubectl_get"
    assert calls[0].arguments["command"] == "pods"


def test_response_output_text_prefers_output_text() -> None:
    response = SimpleNamespace(output_text="hello", output=[])
    assert response_output_text(response) == "hello"


class _FakeResponsesAPI:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("unexpected responses.create call")
        return self._responses.pop(0)


class _FakeAsyncOpenAI:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = _FakeResponsesAPI(responses)

    async def close(self) -> None:
        return None


class _FakeBridge:
    def __init__(self, results: list[BridgeResult]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> BridgeResult:
        self.calls.append((tool_name, arguments or {}))
        return self._results.pop(0)


@pytest.mark.asyncio
async def test_agent_chains_previous_response_id_and_preserve_thinking() -> None:
    settings = AgentSettings(
        DASHSCOPE_API_KEY="sk-test-key-123456",
        AGENT_TOOL_MODE="bridge",
        QWEN_PRESERVE_THINKING=True,
        AGENT_MAX_TURNS=5,
    )

    first = SimpleNamespace(
        id="resp_1",
        output_text="",
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="call_1",
                name="kubectl_get",
                arguments='{"command":"pods -n payments"}',
            )
        ],
    )
    second = SimpleNamespace(
        id="resp_2",
        output_text="Root cause is CrashLoopBackOff; waiting on approval.",
        output=[],
    )

    client = _FakeAsyncOpenAI([first, second])
    bridge = _FakeBridge(
        [
            BridgeResult(
                status_code=200,
                body_text='{"ok":true}',
                pending_approval=False,
                nonce=None,
                expires_in=None,
                timed_out=False,
            )
        ]
    )

    agent = VetoOpsAgent(settings=settings, client=client, bridge=bridge)  # type: ignore[arg-type]
    result = await agent.run_incident("CrashLoopBackOff in payments")

    assert result.stopped_reason == "completed"
    assert result.response_ids == ["resp_1", "resp_2"]
    assert "CrashLoopBackOff" in result.final_text
    assert len(client.responses.calls) == 2

    first_call = client.responses.calls[0]
    second_call = client.responses.calls[1]
    assert "previous_response_id" not in first_call
    assert second_call["previous_response_id"] == "resp_1"
    assert first_call["extra_body"] == {"preserve_thinking": True}
    assert second_call["extra_body"] == {"preserve_thinking": True}
    assert first_call["model"] == "qwen3.7-max"
    assert bridge.calls[0][0] == "kubectl_get"


@pytest.mark.asyncio
async def test_agent_records_pending_approval_nonce() -> None:
    settings = AgentSettings(
        DASHSCOPE_API_KEY="sk-test-key-123456",
        AGENT_TOOL_MODE="bridge",
        AGENT_MAX_TURNS=3,
    )

    first = SimpleNamespace(
        id="resp_1",
        output_text="",
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="call_1",
                name="kubectl_delete",
                arguments='{"command":"namespace evil"}',
            )
        ],
    )
    second = SimpleNamespace(
        id="resp_2",
        output_text="Mutation suspended; awaiting human HMAC approval.",
        output=[],
    )

    client = _FakeAsyncOpenAI([first, second])
    bridge = _FakeBridge(
        [
            BridgeResult(
                status_code=202,
                body_text='{"status":"pending_approval"}',
                pending_approval=True,
                nonce="nonce-xyz",
                expires_in=300,
                timed_out=False,
            )
        ]
    )

    agent = VetoOpsAgent(settings=settings, client=client, bridge=bridge)  # type: ignore[arg-type]
    result = await agent.run_incident("Delete attempt demo")

    assert result.pending_approvals == ["nonce-xyz"]
    assert "awaiting human HMAC approval" in result.final_text
