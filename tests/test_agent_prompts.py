"""Tests for prompts and approval-timeout follow-ups."""

from __future__ import annotations

import pytest

from agent.prompts import (
    SYSTEM_INSTRUCTIONS,
    build_approval_timeout_followup,
    build_incident_prompt,
)


def test_system_instructions_cover_approval_timeouts() -> None:
    lowered = SYSTEM_INSTRUCTIONS.lower()
    assert "pending_approval" in lowered
    assert "timeout" in lowered
    assert "reject" in lowered
    assert "do not retry" in lowered or "tight loop" in lowered


def test_build_incident_prompt() -> None:
    prompt = build_incident_prompt("CrashLoopBackOff in payments")
    assert "CrashLoopBackOff in payments" in prompt
    assert "read-only" in prompt.lower()


def test_build_incident_prompt_rejects_empty() -> None:
    with pytest.raises(ValueError):
        build_incident_prompt("   ")


def test_approval_timeout_followup() -> None:
    message = build_approval_timeout_followup(
        tool_name="kubectl_delete",
        nonce="abc-123",
        detail="expires_in elapsed",
    )
    assert "kubectl_delete" in message
    assert "abc-123" in message
    assert "Do not retry" in message
