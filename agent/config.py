"""Configuration for the Qwen SafeOps agentic engine."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Environment-backed settings for the Qwen Responses API agent."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    dashscope_api_key: str = Field(default="", validation_alias="DASHSCOPE_API_KEY")
    qwen_base_url: str = Field(
        default="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        validation_alias="QWEN_BASE_URL",
    )
    qwen_model: str = Field(default="qwen3.7-max", validation_alias="QWEN_MODEL")
    aegis_proxy_url: str = Field(
        default="http://127.0.0.1:9000",
        validation_alias="AEGIS_PROXY_URL",
    )
    aegis_mcp_sse_url: str = Field(
        default="",
        validation_alias="AEGIS_MCP_SSE_URL",
        description=(
            "Optional public SSE endpoint for native Responses API MCP tools. "
            "When empty, the agent uses the local HTTP bridge against AEGIS_PROXY_URL."
        ),
    )
    tool_mode: Literal["bridge", "remote_mcp"] = Field(
        default="bridge",
        validation_alias="AGENT_TOOL_MODE",
    )
    preserve_thinking: bool = Field(
        default=True,
        validation_alias="QWEN_PRESERVE_THINKING",
    )
    session_cache_enabled: bool = Field(
        default=True,
        validation_alias="QWEN_SESSION_CACHE",
    )
    max_turns: int = Field(default=16, validation_alias="AGENT_MAX_TURNS")
    request_timeout_seconds: float = Field(
        default=120.0,
        validation_alias="AGENT_REQUEST_TIMEOUT_SECONDS",
    )
    mcp_bridge_timeout_seconds: float = Field(
        default=60.0,
        validation_alias="AGENT_MCP_BRIDGE_TIMEOUT_SECONDS",
    )
    approval_wait_hint_seconds: int = Field(
        default=300,
        validation_alias="AGENT_APPROVAL_WAIT_HINT_SECONDS",
    )

    @field_validator("qwen_base_url")
    @classmethod
    def validate_qwen_base_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("QWEN_BASE_URL must be a valid http or https URL")
        normalized = value.strip().rstrip("/")
        if "/api/v2/apps/protocols/" in normalized:
            raise ValueError(
                "QWEN_BASE_URL must use the modern /compatible-mode/v1 path; "
                "legacy /api/v2/apps/protocols/... URLs are deprecated"
            )
        if not normalized.endswith("/compatible-mode/v1"):
            raise ValueError("QWEN_BASE_URL must end with /compatible-mode/v1")
        return normalized

    @field_validator("aegis_proxy_url")
    @classmethod
    def validate_aegis_proxy_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("AEGIS_PROXY_URL must be a valid http or https URL")
        return value.strip().rstrip("/")

    @field_validator("aegis_mcp_sse_url")
    @classmethod
    def validate_aegis_mcp_sse_url(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            return ""
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("AEGIS_MCP_SSE_URL must be a valid http or https URL")
        return candidate

    @field_validator("qwen_model")
    @classmethod
    def validate_qwen_model(cls, value: str) -> str:
        model = value.strip()
        if not model:
            raise ValueError("QWEN_MODEL must not be empty")
        return model

    @field_validator("max_turns")
    @classmethod
    def validate_max_turns(cls, value: int) -> int:
        if value < 1:
            raise ValueError("AGENT_MAX_TURNS must be at least 1")
        return value

    @field_validator("request_timeout_seconds", "mcp_bridge_timeout_seconds")
    @classmethod
    def validate_timeouts(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeouts must be greater than zero")
        return value

    @field_validator("approval_wait_hint_seconds")
    @classmethod
    def validate_approval_wait_hint_seconds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError(
                "AGENT_APPROVAL_WAIT_HINT_SECONDS must be greater than zero"
            )
        return value

    def require_api_key(self) -> str:
        """Return the API key or raise when it is missing."""

        key = self.dashscope_api_key.strip()
        if not key:
            raise ValueError("DASHSCOPE_API_KEY is required to call the Responses API")
        return key


@lru_cache(maxsize=1)
def get_agent_settings() -> AgentSettings:
    """Return a cached agent settings instance."""

    return AgentSettings()
