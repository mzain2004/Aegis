"""Tests for Qwen SafeOps agent configuration and client wiring."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.client import build_default_headers, build_extra_body
from agent.config import AgentSettings, get_agent_settings


@pytest.fixture(autouse=True)
def clear_agent_settings_cache() -> None:
    get_agent_settings.cache_clear()
    yield
    get_agent_settings.cache_clear()


def test_agent_settings_defaults() -> None:
    settings = AgentSettings(DASHSCOPE_API_KEY="sk-test-key-123456")

    assert settings.qwen_model == "qwen3.7-max"
    assert settings.qwen_base_url.endswith("/compatible-mode/v1")
    assert settings.aegis_proxy_url == "http://127.0.0.1:9000"
    assert settings.tool_mode == "bridge"
    assert settings.preserve_thinking is True
    assert settings.session_cache_enabled is True


def test_rejects_legacy_responses_base_path() -> None:
    with pytest.raises(ValidationError):
        AgentSettings(
            DASHSCOPE_API_KEY="sk-test-key-123456",
            QWEN_BASE_URL=(
                "https://dashscope-intl.aliyuncs.com/"
                "api/v2/apps/protocols/compatible-mode/v1"
            ),
        )


def test_build_extra_body_and_session_cache_headers() -> None:
    settings = AgentSettings(
        DASHSCOPE_API_KEY="sk-test-key-123456",
        QWEN_PRESERVE_THINKING=True,
        QWEN_SESSION_CACHE=True,
    )

    assert build_extra_body(settings) == {"preserve_thinking": True}
    assert build_default_headers(settings) == {"x-dashscope-session-cache": "enable"}


def test_can_disable_preserve_thinking_and_session_cache() -> None:
    settings = AgentSettings(
        DASHSCOPE_API_KEY="sk-test-key-123456",
        QWEN_PRESERVE_THINKING=False,
        QWEN_SESSION_CACHE=False,
    )

    assert build_extra_body(settings) == {}
    assert build_default_headers(settings) == {}


def test_require_api_key() -> None:
    settings = AgentSettings(DASHSCOPE_API_KEY="")
    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        settings.require_api_key()
