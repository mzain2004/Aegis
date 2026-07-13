"""OpenAI-compatible Responses API client factory for DashScope / Qwen."""

from __future__ import annotations

from openai import AsyncOpenAI, OpenAI

from agent.config import AgentSettings, get_agent_settings


def build_default_headers(settings: AgentSettings) -> dict[str, str]:
    """Build DashScope headers, including optional session-cache enablement."""

    headers: dict[str, str] = {}
    if settings.session_cache_enabled:
        headers["x-dashscope-session-cache"] = "enable"
    return headers


def build_extra_body(settings: AgentSettings) -> dict[str, bool]:
    """Build non-standard Responses API body fields such as preserve_thinking."""

    body: dict[str, bool] = {}
    if settings.preserve_thinking:
        body["preserve_thinking"] = True
    return body


def create_openai_client(settings: AgentSettings | None = None) -> OpenAI:
    """Create a synchronous OpenAI client pointed at DashScope compatible-mode."""

    cfg = settings or get_agent_settings()
    return OpenAI(
        api_key=cfg.require_api_key(),
        base_url=cfg.qwen_base_url,
        timeout=cfg.request_timeout_seconds,
        default_headers=build_default_headers(cfg),
    )


def create_async_openai_client(settings: AgentSettings | None = None) -> AsyncOpenAI:
    """Create an async OpenAI client pointed at DashScope compatible-mode."""

    cfg = settings or get_agent_settings()
    return AsyncOpenAI(
        api_key=cfg.require_api_key(),
        base_url=cfg.qwen_base_url,
        timeout=cfg.request_timeout_seconds,
        default_headers=build_default_headers(cfg),
    )
